# Instalação

Três caminhos, em ordem de esforço: baixar um aplicativo pronto, executar a partir do
código-fonte com `uv`, ou construir seu próprio instalador.

## Pré-requisitos

| | |
|---|---|
| **Python** | 3.10 ou mais recente, abaixo de 3.14 (`requires-python = ">=3.10,<3.14"`) |
| **Gerenciador de pacotes** | [`uv`](https://docs.astral.sh/uv/) — ele resolve, instala e executa, então não existe passo de `venv` |
| **Disco** | ~700 MB para o ambiente; PyQt6, OpenCV e scikit-image são pacotes grandes |
| **Tela** | Uma sessão gráfica de verdade. Este é um aplicativo GUI e não existe modo headless |

As dependências de execução são quatro, e são instaladas para você:
`numpy`, `opencv-python-headless`, `pyqt6` e `scikit-image`.

!!! note "Por que `opencv-python-headless` e não `opencv-python`"

    Nada neste aplicativo chama `cv2.imshow` ou `cv2.waitKey` — quem exibe é o Qt. O pacote
    `opencv-python` comum traz a própria cópia das bibliotecas Qt, e duas cópias do Qt no mesmo
    processo são a falha clássica
    `Could not load the Qt platform plugin "xcb"`. Se você trocar a dependência na mão, esse é
    o erro que vai aparecer.

### Sistemas operacionais

=== "Linux"

    Totalmente suportado, do código-fonte e como AppImage. Em uma instalação mínima ou em
    contêiner, pode faltar alguma das bibliotecas X às quais o Qt se liga:

    ```bash
    sudo apt install libgl1 libegl1 libxkbcommon-x11-0 libdbus-1-3 \
                     libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
                     libxcb-randr0 libxcb-render-util0 libxcb-shape0
    ```

    O AppImage é construído no Ubuntu 22.04 de propósito: um AppImage se liga à glibc em que
    foi construído, então construir em uma distribuição mais nova produziria um que se recusa a
    iniciar nas mais antigas.

=== "macOS"

    Totalmente suportado a partir do código-fonte. O dmg é **somente arm64** — `cv2` e `scipy`
    publicam pacotes `arm64` e `x86_64` separados e nenhum pacote `universal2`, então um único
    dmg não cobre os dois tipos de Mac. Em um Mac Intel, execute do código-fonte, ou acrescente
    uma entrada `macos-13` à matriz do workflow de release e construa o seu.

    O Qt mapeia ++ctrl++ de um atalho para ++cmd++ aqui, então todo `Ctrl+S` desta documentação
    é `⌘S` no macOS.

=== "Windows"

    Suportado **a partir do código-fonte**. Não há instalador pronto: a receita do Inno Setup
    está no repositório mas nunca foi executada, e o workflow de release deliberadamente não
    inclui Windows na matriz. Trate
    [Construindo um instalador](#construindo-um-instalador) como ponto de partida e não como um
    caminho suportado.

## Início rápido com `uv`

```bash
git clone https://github.com/goncamateus/goncanalyser.git
cd goncanalyser
uv sync
uv run python main.py
```

`uv sync` cria o `.venv` e instala tudo que está fixado em `uv.lock`. Não é preciso ativar
nada — `uv run` usa esse ambiente.

A janela abre vazia, com `Open video, image, or dataset to begin` no lugar do quadro. Passe um
caminho para pular essa etapa:

```bash
uv run python main.py clip.mp4     # um vídeo
uv run python main.py frames/      # uma pasta de imagens, uma por quadro
uv run python main.py shot.png     # uma única imagem
```

As extensões suportadas são `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.webp` e `.ppm`
para imagens e `.mp4`, `.mov`, `.avi`, `.mkv`, `.m4v`, `.webm`, `.mpg` e `.mpeg` para vídeo.

### Grupos opcionais de dependências

O aplicativo roda com as quatro dependências principais. Três recursos trazem suas dependências
à parte, porque nenhuma delas é necessária para abrir uma imagem e todas são grandes:

| Grupo | Comando | Habilita |
|---|---|---|
| `dataset` | `uv sync --group dataset` | **Dataset → Analyse** (matplotlib) e **Dataset → Optimise** (optuna) |
| `rosbag` | `uv sync --group rosbag` | **Rosbag → Extract from ROS bag…** (rosbags, rosbags-image) |
| `build` | `uv sync --no-dev --group build` | PyInstaller, para construir um instalador |
| `dev` | instalado por padrão | pytest |

Se você abrir um desses menus sem o pacote, o aplicativo informa qual **único** pacote falta e
o comando exato para instalá-lo — ele nomeia o pacote e não o grupo, porque o levantamento
precisa de matplotlib, o ajuste precisa de optuna e a extração precisa de rosbags, e nenhum dos
três precisa do pacote do outro.

## Aplicativos prontos

As versões para Linux e macOS são anexadas a cada release com tag na
[página de releases](https://github.com/goncamateus/goncanalyser/releases). Nenhuma delas
precisa de Python nem de clone do repositório.

=== "Linux (AppImage)"

    ```bash
    chmod +x goncanalyser-0.3.0-x86_64.AppImage
    ./goncanalyser-0.3.0-x86_64.AppImage
    ```

    Não há nada a instalar nem a desinstalar — apague o arquivo quando terminar.

=== "macOS (dmg)"

    Abra o dmg, arraste **Analyser** para Applications e, **apenas na primeira execução**,
    clique com o botão direito no aplicativo em Applications, escolha ***Open*** e confirme.

    A build não é notarizada, então um duplo clique da primeira vez leva à recusa do Gatekeeper:
    "cannot be opened because the developer cannot be verified". Botão direito → Open é o
    caminho documentado para isso; depois da primeira vez ele abre normalmente.

O aplicativo empacotado é distribuído **sem** os grupos opcionais, e isso é proposital: o pacote
`dataset` é excluído do bundle, então a build de desktop continua abrindo imagens e vídeo e
avisa o que instalar quando você aciona um trabalho de dataset.

## Construindo um instalador

Uma única receita do PyInstaller, `analyser.spec`, é compartilhada pelas três plataformas; cada
uma tem então um script curto que embrulha o bundle. Um instalador só pode ser construído na
plataforma que ele mesmo tem como alvo — que é exatamente por que o workflow de release existe.

```bash
uv sync --no-dev --group build
```

!!! warning "`--group build` pertence a *todo* `uv run` de uma build"

    Inclusive os que só leem o número da versão. Sem ele, o `uv` ressincroniza o ambiente e
    remove o PyInstaller na hora, e o passo seguinte falha com `No module named PyInstaller`.

=== "Linux"

    ```bash
    uv run --no-dev --group build pyinstaller --noconfirm analyser.spec
    bash packaging/linux/build-appimage.sh
    # -> dist/goncanalyser-0.3.0-x86_64.AppImage
    ```

    Dois passos: o PyInstaller produz `dist/analyser/`, e o script transforma isso em um
    AppImage. O script baixa o `appimagetool` na primeira execução (~10 MB, guardado em
    `build/`) e o roda com `APPIMAGE_EXTRACT_AND_RUN=1`, então FUSE não é necessário.

=== "macOS"

    ```bash
    bash packaging/macos/build-dmg.sh
    # -> dist/goncanalyser-0.3.0-arm64.dmg
    ```

    Um passo, não dois. O `BUNDLE` do spec precisa que `build/icon.icns` exista antes de a build
    começar, e este script é quem o gera — a partir de `packaging/icon.png`, via `sips` e
    `iconutil`, ambos nativos do macOS. Ele então chama o PyInstaller e embrulha o resultado com
    `hdiutil`. Sem Homebrew, sem `create-dmg`.

=== "Windows"

    ```powershell
    uv run --no-dev --group build pyinstaller --noconfirm analyser.spec
    iscc /DAppVersion=0.3.0 packaging\windows\analyser.iss
    # -> dist\goncanalyser-0.3.0-setup.exe
    ```

    Precisa do [Inno Setup](https://jrsoftware.org/isinfo.php). A versão é passada na linha de
    comando para que `pyproject.toml` continue sendo a única fonte da verdade. O instalador é
    por usuário (`PrivilegesRequired=lowest`, sem prompt de UAC) e apenas x64, porque o bundle
    carrega pacotes binários de 64 bits.

    **Este caminho nunca foi executado.** Nenhum release jamais trouxe um `setup.exe`.

### O que a receita faz e o que não faz

`analyser.spec` é `onedir`, não `onefile`: `onefile` descompactaria ~400 MB de `cv2` e `scipy`
em um diretório temporário a cada execução, custando dez segundos de partida a frio e não
ganhando nada, já que um instalador embrulha a saída de qualquer forma.

`hiddenimports` está vazio e `excludes` está curto, ambos deliberadamente. O
`pyinstaller-hooks-contrib` já sabe coletar PyQt6 e scikit-image, e o hook do PyQt6 poda o Qt
até os módulos realmente importados — o único motivo pelo qual a árvore de 260 MB do PyQt6 não
entra no bundle. `tkinter`, `matplotlib`, `optuna` e `dataset` são excluídos para que uma
máquina de build que por acaso tenha o grupo opcional sincronizado não dobre cinquenta megabytes
disso dentro do aplicativo, em silêncio.

UPX e `strip` estão ambos desligados: o UPX corrompe as bibliotecas compartilhadas do Qt com
frequência suficiente para que a economia de tamanho não compense a classe de bug que ele
introduz.

`packaging/icon.png` é um espaço reservado. Substituí-lo pede um PNG de 1024×1024 mais um
`icon.ico` regerado; o `.icns` do macOS é derivado em tempo de build.

## Solução de problemas

??? failure "`Could not load the Qt platform plugin \"xcb\"`"

    Quase sempre duas cópias do Qt no mesmo processo. Verifique se o OpenCV instalado é
    `opencv-python-headless` e não `opencv-python`:

    ```bash
    uv run python -c "import cv2; print(cv2.__file__)"
    uv pip list | grep -i opencv
    ```

    Se o pacote comum estiver presente, remova-o. Se não estiver, faltam as bibliotecas X
    listadas em [Linux](#sistemas-operacionais) acima. `QT_DEBUG_PLUGINS=1` aponta exatamente
    qual `.so` está faltando.

??? failure "`No module named PyInstaller` no meio de uma build"

    Algum `uv run` sem `--group build` ressincronizou o ambiente e o removeu. Coloque
    `--no-dev --group build` em todo `uv run` da build, inclusive naquele que só imprime a
    versão.

??? failure "`FT_Render_Glyph … failed with error 0x62: raster overflow`"

    O `ft2font` do matplotlib e o PyQt6 trazem cada um a sua FreeType, e a que carregar primeiro
    fica com os símbolos do processo inteiro. O `main.py` importa `matplotlib.ft2font` logo no
    topo, antes do PyQt6, justamente para reivindicar a FreeType primeiro — o Qt a toma quando
    constrói o primeiro widget, então importar matplotlib depois que `MainWindow` existe já é
    tarde demais, inclusive a partir de uma thread de trabalho.

    Se você vir isso, esse import foi movido ou removido. Ele parece não usado. Não é.

??? failure "Um menu de dataset diz que falta um pacote"

    Essa é a mensagem pretendida, não um bug — os grupos opcionais não são instalados pelo
    `uv sync`. Rode o comando indicado: `uv sync --group dataset` para Analyse e Optimise,
    `uv sync --group rosbag` para extração de bags.

??? failure "O AppImage não inicia em uma distribuição mais antiga"

    Um AppImage não carrega glibc; ele se liga à do sistema em que foi construído. Construa na
    distribuição mais antiga que você pretende suportar — o workflow de release fixa
    `ubuntu-22.04` exatamente por isso.

??? failure "macOS: \"the developer cannot be verified\""

    A build não é assinada nem notarizada. Clique com o botão direito no aplicativo em
    Applications, escolha *Open* e confirme. Só a primeira execução precisa disso.

??? failure "A janela abre mas a reprodução engasga ou pula quadros"

    Não é defeito. O HOG custa 150–300 ms por quadro a 640×512 e o fluxo óptico denso 30–60 ms,
    ambos mais lentos do que um quadro de vídeo chega. Eles rodam fora da thread da GUI, então
    nada congela, mas a reprodução pula. Desligue o HOG, ou desenhe uma região — uma região de
    200×160 roda a mesma cadeia em um décimo do tempo.

## Verificando a instalação

Todo módulo carrega uma autoverificação executável. Levam segundos, não precisam de fixtures e
são o jeito mais rápido de confirmar que o ambiente está íntegro:

```bash
uv run python -m core.source        # vídeo, pasta e imagem única leem o quadro 0
uv run python -m core.pipeline      # a cadeia sobrevive a toda visualização e todo toggle
uv run python -m features.adjust    # identidade é exata byte a byte; todo limiar é binário
uv run python -m features.color     # imagens conhecidas têm histogramas conhecidos
uv run python -m features.texture   # o tamanho do HOG bate com a geometria; ruído supera plano
uv run python -m features.keypoints # SIFT é 128-d, ORB é 32 bytes, sensibilidade monotônica
uv run python -m features.structure # um quadrado sintético: 1 contorno, 4 cantos, 4 linhas
uv run python -m features.motion    # os seis veem um quadrado em movimento e nenhum vê um parado
uv run python -m features.report    # JSON e CSV fazem ida e volta, dirigidos como ReportThread
uv run python -m ui.viewer          # mapeamento widget->imagem, nas duas orientações de letterbox
uv run python -m ui.controls.base   # grupos são irmãos; todo campo de Settings tem um controle
uv run python -m ui.progress        # a pizza gira; esconder a janela do trabalho a mantém
```

O pacote `dataset` constrói a própria fixture COCO e precisa do seu grupo:

```bash
uv run --group dataset python -m dataset.coco      # polígonos e RLE column-major
uv run --group dataset python -m dataset.stats     # a máscara lê mais clara que o fundo
uv run --group dataset python -m dataset.optimise  # cantos de f(θ) exatos; um estudo supera os padrões
```
