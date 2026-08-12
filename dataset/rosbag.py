"""Pull frames out of a ROS2 bag as PNG/JPG, for the same annotation/tuning
workflow every other `dataset` tool feeds.

The bags this reads are bare `.db3` SQLite files with no `metadata.yaml`
alongside them — `AnyReader` still works: a rosbag2 `.db3`'s `topics` table
carries topic names and types on its own, `metadata.yaml` is only ever a
convenience summary of what is already in there. `default_typestore` is a
fallback for bags that also lack embedded message definitions (older
recordings); it is never used when the bag carries its own.
"""

from pathlib import Path

import cv2
from rosbags.highlevel import AnyReader
from rosbags.image import ImageError, message_to_cvimage
from rosbags.typesys import Stores, get_typestore

IMAGE_MSGTYPES = {"sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage"}


def _reader(bag_path: str) -> AnyReader:
    return AnyReader([Path(bag_path)], default_typestore=get_typestore(Stores.LATEST))


def image_topics(bag_path: str) -> list[str]:
    """Topic names on the bag whose type this tool can turn into a picture."""
    with _reader(bag_path) as reader:
        return [c.topic for c in reader.connections if c.msgtype in IMAGE_MSGTYPES]


def extract(bag_path: str, topic: str, out_dir: str, fmt: str = "png"):
    """Generator yielding (done, total, label); dumps every frame on `topic`.

    Numbered by position in the topic, not by a separate write-count, so a
    frame that fails to decode leaves a gap rather than shifting every frame
    after it — the number in a filename stays the frame's place in the bag.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with _reader(bag_path) as reader:
        connections = [c for c in reader.connections if c.topic == topic]
        if not connections:
            raise ValueError(f"no topic {topic!r} in this bag")
        total = sum(c.msgcount for c in connections)

        written = []
        for index, (connection, _timestamp, rawdata) in enumerate(
            reader.messages(connections=connections)
        ):
            msg = reader.deserialize(rawdata, connection.msgtype)
            try:
                # Not forced to 'bgr8': a depth topic is mono16, and forcing
                # it to 8-bit BGR clips the far side of its range away (a real
                # RealSense Depth_0 topic came back max 56669 -> max 220).
                # Left alone, a colour topic still comes out as a normal BGR
                # array — only a non-colour encoding is affected.
                image = message_to_cvimage(msg)
            except ImageError:
                # An encoding rosbags doesn't know, or a frame whose declared
                # size doesn't match its data — one bad message is not a
                # reason to throw away the frames already written.
                yield index + 1, total, f"frame {index + 1}/{total}"
                continue
            # JPEG is 8-bit only; cv2 silently downcasts anything else to it
            # with just a stderr warning, which for a 16-bit depth frame is
            # the same precision loss forcing 'bgr8' above was avoiding. PNG
            # holds any depth cv2 can write, so it overrides the requested
            # format rather than quietly losing data to it.
            ext = fmt if image.dtype == "uint8" else "png"
            name = f"frame_{index:06d}.{ext}"
            cv2.imwrite(str(out / name), image)
            written.append(name)
            yield index + 1, total, f"frame {index + 1}/{total}"

    return {"dir": str(out), "topic": topic, "frames": len(written), "written": written}


def _fixture(root: Path, count: int = 3, encoding: str = "bgr8", name: str = "fixture") -> str:
    """A tiny bag on disk: `count` solid frames on one topic, `encoding` each.
    Returns the bare `.db3` path, with `metadata.yaml` removed, to match the
    real on-disk situation this tool has to handle. `name` keeps two fixtures
    built under the same `root` from colliding on disk.
    """
    import shutil

    import numpy as np
    from rosbags.rosbag2 import Writer

    typestore = get_typestore(Stores.LATEST)
    Image = typestore.types["sensor_msgs/msg/Image"]
    Header = typestore.types["std_msgs/msg/Header"]
    Time = typestore.types["builtin_interfaces/msg/Time"]

    h, w = 4, 6
    channels, dtype = (1, "uint16") if encoding == "mono16" else (3, "uint8")
    step = w * channels * np.dtype(dtype).itemsize
    bagdir = root / f"{name}_bag"
    with Writer(bagdir, version=9) as writer:
        connection = writer.add_connection(
            "/camera/image", Image.__msgtype__, typestore=typestore
        )
        for i in range(count):
            pixel = i * 10000 if encoding == "mono16" else i * 10
            data = np.full(h * w * channels, pixel, dtype=dtype).view("uint8")
            frame = Image(
                header=Header(stamp=Time(sec=i, nanosec=0), frame_id="cam"),
                height=h, width=w, encoding=encoding, is_bigendian=0,
                step=step, data=data,
            )
            writer.write(connection, i, typestore.serialize_cdr(frame, Image.__msgtype__))

    db3 = next(bagdir.glob("*.db3"))
    bare = root / f"{name}.db3"
    shutil.copy(db3, bare)
    return str(bare)


def _demo() -> None:
    """A bare `.db3`, no `metadata.yaml`: topics list right, frames extract."""
    import tempfile

    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bag = _fixture(root, count=3)
        assert not (Path(bag).parent / "metadata.yaml").exists(), "fixture leaked metadata.yaml"

        assert image_topics(bag) == ["/camera/image"], image_topics(bag)

        dest = root / "out"
        steps = extract(bag, "/camera/image", str(dest), fmt="png")
        seen, result = [], None
        while result is None:
            try:
                seen.append(next(steps))
            except StopIteration as finished:
                result = finished.value
        assert seen[0][:2] == (1, 3) and seen[-1][:2] == (3, 3), (seen[0], seen[-1])
        assert result["frames"] == 3 and len(result["written"]) == 3, result

        for i, name in enumerate(sorted(dest.iterdir())):
            assert name.name == f"frame_{i:06d}.png", name.name
            pixel = cv2.imread(str(name))[0, 0]
            assert (pixel == i * 10).all(), (name, pixel)

        # An unknown topic is a mistake to report, not an empty run to shrug at.
        try:
            list(extract(bag, "/no/such/topic", str(dest)))
            raise AssertionError("expected ValueError for a missing topic")
        except ValueError:
            pass

        # A depth-shaped (mono16) topic: not forced to 'bgr8' (that clipped a
        # real bag's depth range from ~56000 to ~220), and written as PNG even
        # though jpg was requested — JPEG is 8-bit only, and cv2 downcasts
        # anything else to it silently rather than refusing.
        depth_bag = _fixture(root, count=2, encoding="mono16", name="depth")
        depth_dest = root / "depth"
        last_tick = list(extract(depth_bag, "/camera/image", str(depth_dest), fmt="jpg"))[-1]
        assert last_tick[:2] == (2, 2), last_tick
        names = sorted(p.name for p in depth_dest.iterdir())
        assert names == ["frame_000000.png", "frame_000001.png"], names
        second = cv2.imread(str(depth_dest / "frame_000001.png"), cv2.IMREAD_UNCHANGED)
        assert second.dtype == np.uint16 and second[0, 0] == 10000, (second.dtype, second[0, 0])

    print("rosbag ok")


if __name__ == "__main__":
    _demo()
