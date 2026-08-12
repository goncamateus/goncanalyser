# Recursos

Cada recurso, cada parâmetro e o que mover cada um do mínimo ao máximo realmente faz.

Cada seção traz uma descrição, o fluxo de trabalho, uma tabela de parâmetros com a faixa e o
padrão exatos que o controle impõe, uma análise de efeito e uma figura gerada a partir do
aplicativo real.

!!! note "Como ler as tabelas de parâmetros"

    **Campo** é o nome no `settings.json`, então você pode editar um arquivo exportado ou
    escrito à mão e carregá-lo de volta com ++ctrl+l++. **Faixa** é o que o slider ou a caixa
    numérica permite — valores fora dela não podem ser digitados, e vários ainda são limitados
    dentro do próprio recurso (kernels ímpares, na maioria dos casos).

---

## Image Adjustment

**Aba:** Adjust · **Menu:** `Image Adjustment`

![A aba Image Adjustment](../assets/images/tab_adjust.png){ width="400" }

### O que faz

Tudo nesta aba roda **antes** de todos os outros recursos, espaço de cor incluído. Bordas,
keypoints, textura e movimento medem o quadro que esta aba produz, então mudar para LAB
realmente muda o que o SIFT vê. O pré-processamento aqui não é cosmético nem uma prévia — ele
faz parte da medição.

A ordem dentro da aba é a ordem das operações: tom, depois espaço de cor, depois suavização,
depois limiar. Uma região, se houver uma ativa, é recortada antes de tudo isso.

### Tom

Quatro correções aditivas e multiplicativas, aplicadas primeiro.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Brightness | `brightness` | int | −100 … 100 | `0` | Deslocamento aditivo em todos os canais |
| Contrast | `contrast` | float | 0,1 … 3,0 | `1.0` | Ganho multiplicativo. `1.0` é identidade |
| Saturation | `saturation` | float | 0,0 … 3,0 | `1.0` | Ganho no canal S do HSV. `1.0` é identidade |
| Gamma | `gamma` | float | 0,1 … 3,0 | `1.0` | `<1` escurece, `>1` levanta as sombras |

#### Análise de efeito

**Brilho −100 → +100.** Em −100 tudo abaixo do cinza médio satura em preto e o detalhe nas
sombras se perde de vez — todo recurso a jusante vê o quadro cortado, não o original. Em +100
são as altas luzes que saturam, o que é a direção mais danosa para detectores de keypoints: uma
região branca e plana não tem gradiente, então SIFT e Canny não encontram nada ali.

![Brilho de −100 a +100](../assets/images/adjust_brightness.jpg)

**Contraste 0,1 → 3,0.** Em 0,1 o quadro colapsa em direção ao preto e o histograma vira um
pico — o Otsu, que escolhe seu nível a partir desse histograma, então quase não tem o que
separar. Em 3,0 os meios-tons se esticam para os dois extremos, o que facilita muito posicionar
um limiar e ao mesmo tempo destrói os extremos. A faixa útil para a maior parte do ajuste é
0,7–1,6.

![Contraste de 0,1 a 3,0](../assets/images/adjust_contrast.jpg)

**Saturação 0,0 → 3,0.** Em `0.0` o quadro fica cinza — não convertido para escala de cinza,
mas com a cor removida, o que é diferente de escolher `Grayscale` abaixo porque o array continua
com três canais. Acima de `1.0` a separação de cor aumenta, o que ajuda se você for limiarizar
em um canal de cor e não faz absolutamente nada para os recursos que só usam escala de cinza.

![Saturação de 0,0 a 3,0](../assets/images/adjust_saturation.jpg)

**Gama 0,1 → 3,0.** O não linear. Abaixo de `1.0` ele comprime as sombras e expande as altas
luzes; acima de `1.0` faz o inverso, que é o ajuste a buscar quando a coisa que você quer é
escura e o fundo não é. Diferente do contraste, ele não satura — a curva é monotônica em toda a
faixa — então é o mais seguro dos dois quando o detalhe importa.

![Gama de 0,1 a 3,0](../assets/images/adjust_gamma.jpg)

### Espaço de cor

| Nome | Campo | Tipo | Valores | Padrão |
|---|---|---|---|---|
| Colour space | `color_space` | escolha | `BGR`, `Grayscale`, `HSV`, `LAB`, `HLS` | `BGR` |

Convertido **antes** de tudo o que vem depois. HSV, HLS e LAB são desenhados como canais crus —
ou seja, em falsa cor — porque não há forma significativa de exibi-los de outro jeito, e porque
o que importa é o que os *recursos* leem, não a aparência.

#### Análise de efeito

`Grayscale` é o mais barato e elimina qualquer chance de um artefato de cor guiar um detector.
`HSV` coloca o matiz no canal 0, o que torna trivial um limiar de matiz e torna sem sentido
qualquer conversão para cinza a jusante — `to_gray` de uma imagem HSV não é luminância. `LAB`
separa a luminosidade da cor com mais fidelidade que o HSV, a um custo ligeiramente maior. Nada
aqui está errado; o que muda é o que "brilho" significa para todo operador seguinte.

![Os cinco espaços de cor](../assets/images/adjust_colorspace.jpg)

### Suavização

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Kind | `blur_kind` | escolha | `None`, `Gaussian`, `Median` | `None` | Qual filtro |
| Kernel | `blur` | int | 0 … 31 | `0` | `0` ou `1` desliga; valores pares sobem para o ímpar seguinte |

#### Análise de efeito

**Kernel 0 → 31.** Em 0 ou 1 o filtro está desligado. Kernels pequenos (3–7) removem ruído de
sensor e preservam estrutura; grandes (15+) removem estrutura também, o que ocasionalmente é o
que se quer — um quadro fortemente desfocado limiariza em poucas regiões grandes em vez de
centenas de manchas. Todo aumento custa nitidez de borda, e a resposta do Canny cai junto.

**A mediana supera a gaussiana em ruído sal-e-pimenta** e mantém bordas mais nítidas no mesmo
kernel, porque toma um valor de pixel real em vez de uma média ponderada da vizinhança. A
gaussiana é mais barata e é o padrão certo para ruído de sensor aproximadamente normal.

![None, Gaussian e Median nos kernels 9 e 31](../assets/images/adjust_blur.jpg)

### Limiar

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Kind | `threshold_kind` | escolha | `None`, `Binary`, `Binary inverted`, `Otsu`, `Adaptive mean`, `Adaptive Gaussian` | `None` | Qual regra |
| Level | `threshold` | int | 0 … 255 | `127` | Ponto de corte. **Ignorado** pelo Otsu e pelos dois modos adaptativos |
| Adaptive neighbourhood | `adaptive_block` | int | 3 … 51 | `11` | Só os dois modos adaptativos. Ímpar, limitado a ≥ 3 |

!!! warning "Selecionar um modo de limiar binariza o quadro de trabalho"

    Não só a visualização `Threshold` — a visualização `Source` também fica em preto e branco, e
    todo recurso depois deste ponto mede uma imagem binária. É isso que faz do limiar parte do
    pré-processamento e não uma opção de exibição.

    Deixe o combo em `None` e a tela `Threshold` continua sendo derivada, em `Binary` usando
    `Level`, para que o localizador de contornos tenha o que ler e o resto da cadeia mantenha o
    quadro colorido.

#### Análise de efeito

**Nível 0 → 255** com `Binary`: em 0 tudo é primeiro plano e a máscara fica totalmente branca;
em 255 nada é. A faixa interessante é estreita e depende da cena, que é exatamente por que isso
é um slider e não um argumento.

![Limiar binário nos níveis 60 a 210](../assets/images/adjust_threshold_level.jpg)

**Os cinco modos.** `Binary` e `Binary inverted` são o mesmo corte em direções opostas — use o
invertido quando a coisa que você quer for mais escura que o entorno. O `Otsu` escolhe o nível
sozinho maximizando a variância entre classes, o que é excelente em um histograma bimodal e
arbitrário em um histograma plano. Os dois modos adaptativos calculam um nível por vizinhança em
vez de um para o quadro, que é o que se precisa sob iluminação desigual — e que produz manchas
em regiões lisas, porque uma vizinhança sem estrutura real ainda assim é dividida ao meio.

**Vizinhança adaptativa 3 → 51.** Blocos pequenos seguem de perto a iluminação local e
transformam ruído em estrutura; blocos grandes se aproximam de um limiar global e param de
compensar o gradiente pelo qual você ligou o modo adaptativo.

![Os cinco modos de limiar](../assets/images/adjust_threshold_kind.jpg)

### Selection — região de interesse

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Limit analysis to a region | `roi_on` | bool | — | `false` | Interruptor principal |
| X | `roi_x` | int | 0 … largura do quadro | `0` | Borda esquerda, px |
| Y | `roi_y` | int | 0 … altura do quadro | `0` | Borda superior, px |
| W | `roi_w` | int | 0 … largura do quadro | `0` | Largura. **`0` significa até a borda direita** |
| H | `roi_h` | int | 0 … altura do quadro | `0` | Altura. **`0` significa até a borda inferior** |

Tudo é medido **somente dentro do retângulo**. A moldura ao redor permanece na tela como
contexto e nunca chega aos números. As coordenadas exportadas são traduzidas de volta para
pixels do quadro inteiro, então um CSV significa a mesma coisa com região e sem região.

#### Análise de efeito

A região não é um recorte da exibição, é um recorte da *análise*, e acontece primeiro. O Otsu
dentro de uma região escolhe seu nível apenas a partir do histograma daquela região; um desfoque
dentro de uma região não lê nenhum pixel de fora dela. Ambas as afirmações seriam falsas se o
recorte acontecesse por último, e ambas são o motivo de não acontecer.

O segundo efeito é velocidade: SIFT + HOG sobre um quadro completo de 640×512 custa 202 ms e
sobre uma região de 200×160 custa 21 ms, que é a diferença entre pular quadros e não pular.

![Otsu com a região desligada e ligada — o mesmo quadro, dois níveis diferentes](../assets/images/adjust_roi.jpg)

Veja [Controles → Região de interesse](controls.md#regiao-de-interesse) para o fluxo de arraste e
caixas numéricas.

---

## Histograma de cor

**Aba:** Global · **Menu:** `Global`

![A aba Global](../assets/images/tab_global.png){ width="400" }

### O que faz

Histogramas de três canais do quadro pré-processado, desenhados com `cv2.polylines` em uma tela
de 512×256 que é ao mesmo tempo prévia no painel e uma `View` completa. **Sempre medidos** —
três chamadas a `calcHist` custam menos que a caixa de seleção que permitiria desligá-los.

### Como usar

1. Escolha um espaço no grupo **Colour histogram**.
2. Leia na prévia do painel, ou coloque `View` em `Histogram` para o gráfico em tamanho real.
3. As médias e desvios-padrão dos canais aparecem na barra de status e no `metrics.csv`; as
   contagens por bin vão para `histogram.csv` na exportação.

| Nome | Campo | Tipo | Valores | Padrão |
|---|---|---|---|---|
| Space | `hist_space` | escolha | `RGB`, `HSV`, `LAB` | `RGB` |

#### Análise de efeito

`RGB` mostra os três canais como estão armazenados, e suas três curvas se movem juntas sob
qualquer mudança de exposição. `HSV` separa o matiz da intensidade, então um pico de matiz fica
onde está quando a iluminação muda — que é o que faz dele o espaço certo para encontrar um
objeto colorido. `LAB` coloca luminosidade perceptual em um canal e cor em dois, então um
histograma de `L` é a coisa mais próxima aqui de "o que um humano chamaria de brilho".

![O mesmo quadro em RGB, HSV e LAB](../assets/images/color_histogram.jpg)

!!! note

    O histograma é um gráfico, não um quadro. Ele permanece 512×256 qualquer que seja a fonte,
    que é por que não se pode desenhar uma região enquanto ele é a visualização ativa e por que
    ele nunca é espremido dentro do retângulo de uma região.

---

## HOG — Histograma de Gradientes Orientados

**Aba:** Global

### O que faz

Divide o quadro em células, monta um histograma das direções de gradiente em cada uma, normaliza
sobre blocos de células e devolve tanto o descritor quanto uma visualização. É o descritor
clássico de forma — sobre o que um detector de pedestres era construído antes das CNNs.

### Como usar

1. Marque **Compute HOG**.
2. Coloque `View` em `HOG` para ver a visualização em tamanho real, ou acompanhe a prévia do
   painel.
3. Ajuste `Cell` primeiro — ele domina o resultado —, depois as orientações, depois o bloco.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Compute HOG | `hog_on` | bool | — | `false` | Desligado por padrão por ser o caro |
| Orientations | `hog_orientations` | int | 2 … 18 | `9` | Bins de direção de gradiente por célula |
| Cell (px) | `hog_cell` | int | 2 … 32 | `8` | Pixels por célula, quadrada |
| Block (cells) | `hog_block` | int | 1 … 6 | `2` | Células por bloco de normalização |

!!! danger "O HOG custa 150–300 ms por quadro a 640×512"

    Isso é mais lento do que um quadro de vídeo chega. Ele roda na thread de trabalho, então a
    janela nunca congela, mas **a reprodução vai pular quadros enquanto ele estiver ligado**.
    Desenhe uma região para torná-lo utilizável em vídeo.

#### Análise de efeito

**Célula 2 → 32.** Em 2 px o descritor é enorme, extremamente sensível a ruído e lento; em 32 px
cada célula faz média de tudo exceto a forma mais grosseira. Os clássicos 8 px são um ponto
ótimo real para objetos em escala humana em resoluções típicas — escale com o seu objeto, não
com a sua imagem.

**Orientações 2 → 18.** Dois bins só conseguem distinguir horizontal de vertical. Nove bins
sobre 180° é a configuração não sinalizada padrão e separa a maioria das formas. Acima de uns 12
os bins extras codificam sobretudo ruído, e o descritor cresce linearmente em custo.

**Bloco 1 → 6.** A normalização por bloco é o que dá ao HOG sua invariância à iluminação. Em 1
praticamente não há normalização, então uma mudança de brilho desloca o descritor inteiro. Em 6
a janela de normalização cobre tanto do quadro que o contraste local é achatado.

![HOG com células de 4, 8 e 16 px e orientações 4, 9 e 18](../assets/images/texture_hog.jpg)

---

## LBP — Padrões Binários Locais

**Aba:** Global

### O que faz

Compara cada pixel a `P` vizinhos em um círculo de raio `R` e codifica a comparação como um
código binário. Barato, tolerante a rotação na forma `uniform` e um descritor de textura
genuinamente bom para classificar material e superfície.

### Como usar

1. Marque **Compute LBP**.
2. Coloque `View` em `LBP` para ver a imagem de códigos.
3. Leia `lbp_entropy` na barra de status — alto para textura variada, baixo para plana.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Compute LBP | `lbp_on` | bool | — | `false` | |
| Neighbours (P) | `lbp_points` | int | 1 … 24 | `8` | Pontos de amostra no círculo |
| Radius (R) | `lbp_radius` | int | 1 … 8 | `1` | Raio do círculo em px |
| Method | `lbp_method` | escolha | `uniform`, `default`, `ror`, `nri_uniform`, `var` | `uniform` | As variantes de LBP do scikit-image |

#### Análise de efeito

**P e R juntos definem a escala da textura.** `P=8, R=1` lê a vizinhança imediata e responde a
grão fino. `P=16, R=2` e `P=24, R=4` leem estrutura progressivamente mais grosseira e custam
proporcionalmente mais. Aumentar `R` sem aumentar `P` subamostra o círculo e introduz aliasing —
os pares convencionais são `(8,1)`, `(16,2)` e `(24,3)`.

**Método.** `uniform` colapsa os códigos com no máximo duas transições de bit em `P+1` bins e
todo o resto em um só, o que é ao mesmo tempo compacto e invariante à rotação — é o padrão
certo. `default` mantém todos os 2^P códigos. `ror` rotaciona cada código até seu mínimo, o que é
invariante à rotação sem o colapso uniforme. `nri_uniform` é uniforme *sem* invariância à
rotação, então preserva informação de orientação. `var` devolve a variância local em vez de um
código, o que é contraste e não padrão.

![LBP em P=8/R=1, P=8/R=3, P=16/R=2 e P=24/R=4](../assets/images/texture_lbp.jpg)

---

## Keypoints

**Aba:** Local · **Menu:** `Local`

![A aba Local](../assets/images/tab_local.png){ width="400" }

### O que faz

Encontra pontos distintivos e repetíveis e calcula um descritor para cada um, de modo que o
mesmo ponto físico possa ser reconhecido em outro quadro. Dois detectores estão disponíveis:

- **SIFT** — descritor float de 128 dimensões, invariante a escala e rotação, mais
  discriminativo, lento.
- **ORB** — descritor binário de 32 bytes, rápido o suficiente para vídeo, menos discriminativo.

!!! info "Por que SURF, AKAZE, BRISK e KAZE não estão aqui"

    Não é omissão nem pendência. O **SURF** é patenteado, vive atrás de
    `OPENCV_ENABLE_NONFREE`, e nenhum pacote publicado o habilita — nem mesmo o
    `opencv-contrib-python`; ele exige compilação a partir do fonte. **AKAZE, BRISK e KAZE**
    estão totalmente ausentes dos bindings Python do `opencv-python` 5.0 — `cv2.AKAZE` não
    existe. **ALIKED e DISK**, que a 5.0 acrescenta no lugar deles, exigem arquivos de modelo
    ONNX que não são distribuídos. O que existe são os dois que funcionam.

### Como usar

1. Escolha `SIFT` ou `ORB`.
2. Mova **Sensitivity** até obter a densidade de pontos desejada.
3. Limite a quantidade com **Max keypoints** se a sobreposição ficar ilegível.
4. Desligue **Draw scale and orientation** quando houver milhares deles.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Detector | `detector` | escolha | `None`, `SIFT`, `ORB` | `None` | |
| Sensitivity | `kp_sensitivity` | float | 0,0 … 1,0 | `0.5` | Um controle normalizado para os dois detectores |
| Max keypoints | `kp_max` | int | 10 … 5000 | `500` | Os mais fortes por resposta são mantidos |
| Octave layers | `kp_octaves` | int | 1 … 8 | `3` | Profundidade do espaço de escala |
| Edge threshold | `kp_edge` | float | 1 … 50 | `10.0` | Rejeita pontos que ficam ao longo de uma borda |
| Draw scale and orientation | `kp_rich` | bool | — | `true` | Keypoints ricos em vez de pontos simples |

#### Análise de efeito

**Sensibilidade 0,0 → 1,0.** Os limiares nativos dos dois detectores não são números comparáveis
— o SIFT quer um `contrastThreshold` em torno de 0,04 e o ORB um `fastThreshold` em torno de 20 —
então o painel expõe um único controle normalizado e o mapeia para a faixa real de cada
detector: SIFT `0.16 → 0.005`, ORB `60 → 3`. Ambas as faixas vão de estrito a permissivo, então
**para cima sempre significa mais keypoints**, qualquer que seja o detector selecionado.

Em 0,0 você obtém apenas os poucos cantos de mais alto contraste, que é o que se quer para
casamento com linha de base larga. Em 1,0 você obtém milhares, a maioria ruído, e `Max keypoints`
passa a ser o que de fato decide o que você vê.

![SIFT com sensibilidade 0,1, 0,5 e 0,9](../assets/images/keypoints_sensitivity.jpg)

**Max keypoints 10 → 5000.** Um teto, não uma meta — o detector encontra o que encontra e os
mais fortes por resposta sobrevivem. Aumentá-lo além do que a sensibilidade produz não muda
nada.

**Octave layers 1 → 8.** Profundidade do espaço de escala. Mais camadas encontram
características em uma faixa mais ampla de tamanhos e custam proporcionalmente mais tempo. 3 é o
valor padrão do SIFT e está certo a menos que seus objetos variem de tamanho em mais de umas
4 vezes.

**Edge threshold 1 → 50.** Rejeita keypoints que ficam ao longo de uma borda em vez de em um
canto — eles são mal localizados em uma direção, então deslizam ao longo da borda entre quadros e
casam mal. Valores baixos rejeitam agressivamente; valores altos mantêm quase tudo.

![SIFT vs ORB, keypoints ricos e pontos simples](../assets/images/keypoints_detectors.jpg)

---

## Bordas

**Aba:** Structures · **Menu:** `Structures`

![A aba Structures](../assets/images/tab_structures.png){ width="400" }

### O que faz

Três operadores de borda, um de cada vez, desenhados na tela `Edges`.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Kind | `edge_kind` | escolha | `None`, `Canny`, `Sobel`, `Laplacian` | `None` | |
| Canny low | `canny_lo` | int | 0 … 500 | `100` | Abaixo disso um pixel nunca é borda |
| Canny high | `canny_hi` | int | 0 … 500 | `200` | Acima disso ele sempre é |
| Sobel kernel | `sobel_k` | int | 1 … 7 | `3` | Ímpar, limitado a 7 |
| Sobel dx | `sobel_dx` | int | 0 … 2 | `1` | Ordem da derivada em x |
| Sobel dy | `sobel_dy` | int | 0 … 2 | `1` | Ordem da derivada em y. `dx` e `dy` não podem ser 0 ao mesmo tempo |
| Laplacian kernel | `lap_k` | int | 1 … 31 | `3` | Ímpar |

#### Análise de efeito

**Canny low e high.** O Canny é um limiar por histerese: acima de `high` um pixel é sempre borda,
abaixo de `low` nunca, e entre os dois somente se estiver conectado a uma borda forte. Baixar
`low` estende bordas existentes e junta as interrompidas; baixar `high` cria novas bordas
semente e, a partir de certo ponto, inunda a imagem. A proporção convencional é 1:2 ou 1:3 —
`100/200` é o padrão por isso. `30/90` em um quadro ruidoso produz uma teia densa; `200/400`
mantém apenas as fronteiras mais fortes.

![Canny em 30/90, 100/200 e 200/400](../assets/images/edges_canny.jpg)

**Kernel Sobel 1 → 7.** Um kernel maior é uma janela de derivada mais larga: menos sensível a
ruído, bordas mais grossas e menos precisamente localizadas. O Sobel devolve uma *magnitude* de
gradiente, não um mapa binário, que é por que ele parece um quadro em relevo em vez de um
desenho de linhas — e por que o Hough não pode usá-lo diretamente.

**Sobel dx / dy.** `dx=1, dy=0` encontra apenas bordas verticais, `dx=0, dy=1` apenas
horizontais, `dx=1, dy=1` as duas. Segunda ordem (`2`) responde à mudança do gradiente em vez do
gradiente, o que destaca cristas em vez de degraus.

**Kernel Laplaciano 1 → 31.** A segunda derivada nas duas direções ao mesmo tempo, então é
isotrópico e não tem parâmetro de direção. É o mais sensível a ruído dos três em kernels
pequenos; kernels grandes o suavizam em uma resposta larga.

![Canny, Sobel com kernel 3 e 7, e Laplaciano com kernel 5](../assets/images/edges_kinds.jpg)

---

## Hough

**Aba:** Structures

### O que faz

Encontra linhas ou círculos por votação em um espaço de parâmetros. Cada pixel de borda candidato
vota em toda linha ou círculo que poderia passar por ele, e os picos são as respostas.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Kind | `hough_kind` | escolha | `None`, `Lines`, `Circles` | `None` | |
| Votes | `hough_thresh` | int | 1 … 400 | `120` | Limiar do acumulador — quanta evidência é necessária |
| Min length / min distance | `hough_min_len` | int | 1 … 400 | `50` | Menor segmento de linha mantido; para círculos, a menor distância entre dois centros |
| Max gap | `hough_max_gap` | int | 0 … 100 | `10` | Só linhas: uma falha desse tamanho ainda conta como uma linha |

!!! note "O Hough constrói o próprio Canny"

    Sempre, a partir de `Canny low` e `Canny high` acima — mesmo quando o combo de bordas está em
    Sobel ou `None`. Ele precisa de um mapa de bordas *binário*, e uma magnitude Sobel não é um.
    Ou seja, os dois controles do Canny afetam o Hough esteja o Canny selecionado ou não.

#### Análise de efeito

**Votos 1 → 400.** De longe o controle mais importante aqui. Valores baixos devolvem centenas de
linhas espúrias ajustadas a ruído; valores altos devolvem apenas bordas retas longas e
inequívocas, e a partir de certo ponto nada. Ele escala com o tamanho da imagem, porque uma linha
mais longa simplesmente tem mais pixels para votar — um limiar calibrado em 640×480 não encontra
nada em 320×240.

**Comprimento mínimo 1 → 400.** Um pós-filtro de comprimento de segmento, então descarta
fragmentos curtos sem mudar o que o acumulador encontrou.

**Falha máxima 0 → 100.** Em 0, qualquer interrupção divide uma linha em duas. Aumentar preenche
linhas tracejadas e bordas pontilhadas — e, acima da escala das falhas reais da sua cena, funde
segmentos colineares genuinamente separados em um só.

![Linhas de Hough com 60, 120 e 240 votos](../assets/images/hough_lines.jpg)

---

## Cantos

**Aba:** Structures

### O que faz

Encontra pontos onde o gradiente da imagem é forte em duas direções ao mesmo tempo. Ao contrário
dos keypoints, cantos não carregam descritor — são localizações, não identidades.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Kind | `corner_kind` | escolha | `None`, `Harris`, `Shi-Tomasi` | `None` | |
| Max corners | `corner_max` | int | 1 … 2000 | `200` | |
| Quality | `corner_quality` | float | 0,001 … 0,2 | `0.01` | Fração da resposta mais forte que um canto precisa atingir |
| Min distance (px) | `corner_min_dist` | int | 1 … 100 | `10` | Só Shi-Tomasi |
| Harris k | `harris_k` | float | 0,01 … 0,2 | `0.04` | Só Harris. Mais baixo detecta mais |

#### Análise de efeito

**Qualidade 0,001 → 0,2.** Relativa, não absoluta: um canto precisa marcar pelo menos essa fração
do melhor canto do quadro. Isso a torna estável a mudanças de exposição e instável a mudanças de
cena — um único canto muito forte eleva a régua para todos os outros. Em 0,001 quase todo máximo
local se qualifica; em 0,2 apenas cantos dentro de um fator cinco do melhor.

**Distância mínima 1 → 100.** Impõe espaçamento, então os cantos se espalham pelo quadro em vez
de se aglomerarem no único objeto de alto contraste. Aumente quando a sobreposição virar uma
mancha sólida em um canto da imagem.

**Harris k 0,01 → 0,2.** O termo de sensibilidade na função de resposta de Harris. Valores mais
baixos tornam a resposta mais permissiva e detectam mais cantos — inclusive pontos de borda que
não são realmente cantos. 0,04–0,06 é a faixa convencional.

**Harris vs Shi-Tomasi.** O Shi-Tomasi usa diretamente o menor dos dois autovalores em vez da
aproximação determinante-menos-traço de Harris, o que o torna um pouco mais confiável e um pouco
mais lento; é também o que tem o controle de espaçamento.

![Harris com k=0,04 e 0,15, Shi-Tomasi com qualidade 0,01 e 0,1](../assets/images/corners.jpg)

---

## Contornos

**Aba:** Structures

### O que faz

Traça os contornos de regiões conectadas na **imagem `Threshold`** — não no mapa de bordas.
Encontrar contornos exige uma imagem binária, e limiarizar é como se obtém uma. Cada contorno
contribui com área, perímetro, caixa delimitadora e pai para o `contours.csv`, e o resultado
preenchido é a tela `Contour mask` — que é também a máscara pontuada pelo otimizador de dataset.

### Como usar

1. Ajuste o limiar na aba Image Adjustment **primeiro**, e olhe a visualização `Threshold` para
   ver exatamente o que está sendo entregue ao localizador.
2. Marque **Find contours**.
3. Aumente **Min area** até o ruído sumir.
4. Mude para `Contour mask` para ver a máscara, ou fique em `Source` para as caixas sobre o
   quadro.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Find contours | `contours_on` | bool | — | `false` | |
| Mode | `contour_mode` | escolha | `External`, `List`, `Tree` | `External` | Modo de recuperação |
| Min area (px) | `contour_min_area` | int | 0 … 5000 | `50` | |
| Bounding boxes | `contour_boxes` | bool | — | `true` | Desenha as caixas além dos contornos |

#### Análise de efeito

**Área mínima 0 → 5000.** O filtro de ruído. Em 0 toda mancha do limiar vira um contorno — em um
quadro real são centenas deles, e o CSV herda cada um. Em 5000 apenas regiões substanciais
sobrevivem. É medida em pixels do quadro *analisado*, então uma região muda o que um dado número
significa.

![Área mínima em 0, 50, 500 e 5000 px](../assets/images/contours_min_area.jpg)

**Modo.** `External` mantém apenas os contornos mais externos — um anel vira um contorno, não
dois. `List` devolve todos os contornos sem hierarquia. `Tree` devolve todos os contornos *com* a
hierarquia, e é o único modo que preenche a coluna `parent` no CSV exportado. Use `External` para
contar objetos e `Tree` quando buracos importam.

![Visualização Threshold, máscara de contorno e os mesmos contornos como caixas](../assets/images/contours_mask.jpg)

---

## Blobs

**Aba:** Structures

### O que faz

`cv2.SimpleBlobDetector` — encontra regiões aproximadamente convexas e as filtra por área,
circularidade e convexidade. Onde os contornos dão todas as formas, os blobs dão as redondas.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Find blobs | `blobs_on` | bool | — | `false` | |
| Min area (px) | `blob_min_area` | int | 1 … 5000 | `50` | |
| Max area (px) | `blob_max_area` | int | 2 … 50000 | `5000` | |
| Min circularity | `blob_circularity` | float | 0,0 … 1,0 | `0.0` | `0` desliga o filtro; `1` é um círculo perfeito |
| Min convexity | `blob_convexity` | float | 0,0 … 1,0 | `0.0` | `0` desliga; valores baixos permitem reentrâncias |
| Dark blobs on light | `blob_dark` | bool | — | `true` | A polaridade padrão do OpenCV |

#### Análise de efeito

**Área mínima e máxima** são uma faixa, não um piso — um blob maior que o máximo é descartado com
a mesma firmeza que um menor que o mínimo, o que surpreende quem espera que o máximo seja um
teto. Se nada é detectado, alargue a faixa antes de mexer em qualquer outra coisa.

**Circularidade 0 → 1** é `4πA/P²`: 1 é um círculo, ~0,78 um quadrado, e uma forma longa e fina
tende a 0. Qualquer coisa acima de cerca de 0,8 rejeita tudo que não seja quase redondo.

**Convexidade 0 → 1** é a área do blob dividida pela área do seu fecho convexo. Rejeita formas
com mordidas — tipicamente dois objetos sobrepostos detectados como um. Valores baixos toleram
reentrâncias; valores altos exigem um contorno limpo.

**Dark blobs on light** inverte a polaridade. Se seus objetos são claros sobre fundo escuro — o
caso usual de uma imagem térmica ou de uma micrografia de fluorescência — desmarque, ou você vai
encontrar os vãos entre seus objetos em vez dos objetos.

![Blobs com área 50–5000 e 500–50000](../assets/images/blobs.jpg)

---

## Movimento

**Aba:** Motion · **Menu:** `Motion`

![A aba Motion](../assets/images/tab_motion.png){ width="400" }

### O que faz

O único recurso que mede o eixo do tempo, o que o torna também o único com estado por trás. Seis
algoritmos, todos reportando a mesma coisa: uma imagem de movimento 0–255, que um único limiar
**Sensitivity** compartilhado então corta em uma máscara.

| Algoritmo | O que é | Quando usar |
|---|---|---|
| `MOG2` | Modelo de fundo por mistura de gaussianas | Uso geral, adapta-se a mudanças graduais |
| `KNN` | Modelo de fundo por k vizinhos mais próximos | Mesma função do MOG2, melhor com primeiro plano esparso |
| `Farneback` | Fluxo óptico denso | Quando a *forma* da coisa em movimento importa |
| `Lucas-Kanade` | Fluxo esparso em cantos rastreados, cada vetor pintado como um disco | Rápido, mas um disco não é uma segmentação |
| `Frame difference` | Diferença absoluta simples | O mais simples possível, sem modelo, sem adaptação |
| `Three-frame difference` | Mínimo de duas diferenças consecutivas | Elimina o fantasma que a diferença simples deixa *atrás* do objeto |

Como os seis normalizam para a mesma imagem 0–255, **os controles significam a mesma coisa em
todos eles** e trocar de algoritmo não é reaprender o painel. O fluxo óptico é escalado na
entrada — 8 px/quadro lê como escala cheia, via `motion.FLOW_GAIN` caso isso precise de
calibração para uma cena lenta e grande-angular.

![Os mesmos 40 quadros pelos seis algoritmos, exibidos como Motion mask](../assets/images/motion_algorithms.jpg)

### Controles compartilhados

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Algorithm | `motion_algo` | escolha | `None`, `MOG2`, `KNN`, `Farneback`, `Lucas-Kanade`, `Frame difference`, `Three-frame difference` | `None` | |
| Sensitivity | `motion_threshold` | int | 1 … 255 | `25` | Níveis de cinza de mudança que contam como movimento. Menor encontra mais |
| Noise removal | `motion_open` | int | 0 … 15 | `3` | Kernel de abertura morfológica. `0` ou `1` desliga |

#### Análise de efeito

**Sensibilidade 1 → 255.** Em 1 quase todo pixel que mudou minimamente é primeiro plano,
inclusive ruído de sensor e artefatos de compressão. Em 255 nada é. Note que ela **não tem efeito
sobre MOG2 e KNN**, que reportam uma decisão binária em vez de uma magnitude — para esses dois,
os parâmetros do próprio modelo são a sensibilidade.

![Sensibilidade 5, 25, 80 e 200 no MOG2](../assets/images/motion_sensitivity.jpg)

**Remoção de ruído 0 → 15.** Uma abertura morfológica: erode e depois dilata, o que apaga
qualquer coisa mais fina que o kernel e deixa o resto aproximadamente do tamanho original. É a
primeira coisa a buscar quando a máscara está manchada. Acima de uns 9 ela começa a comer as
partes finas de objetos reais.

![Remoção de ruído 0, 3, 9 e 15 em uma diferença de quadros](../assets/images/motion_open.jpg)

### Subtração de fundo — MOG2 e KNN

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Learning rate | `motion_learning` | float | −1,0 … 1,0 | `-1.0` | `-1` deixa o OpenCV derivar do History; maior esquece o fundo mais rápido |
| MOG2 history | `mog_history` | int | 1 … 2000 | `500` | Quadros a partir dos quais o modelo é construído |
| MOG2 variance | `mog_var` | float | 1 … 100 | `16.0` | Menor é mais sensível |
| MOG2 shadows | `mog_shadows` | bool | — | `true` | Detectar sombras (nunca contadas como movimento) |
| KNN history | `knn_history` | int | 1 … 2000 | `500` | |
| KNN distance | `knn_dist` | float | 10 … 2000 | `400.0` | Distância quadrática até um vizinho |
| KNN shadows | `knn_shadows` | bool | — | `true` | |

#### Análise de efeito

**History 1 → 2000.** Quanto passado o modelo promedia. Históricos curtos se adaptam rápido, o
que significa que um objeto lento é absorvido pelo fundo e desaparece; históricos longos se
lembram de uma cena que não existe mais, então um ajuste de câmera acende o quadro inteiro por
centenas de quadros. **Uma pluma que nunca se move acaba *virando* fundo** — esse comportamento é
o que History e Learning rate existem para controlar.

**Learning rate −1 → 1.** `-1` deriva a taxa do History, que é o que se quer quase sempre. `0`
congela o modelo — nada é aprendido depois dos primeiros quadros, útil quando você tem imagens
limpas de fundo para inicializá-lo. `1` reaprende o fundo a cada quadro, o que torna invisível
tudo exceto o movimento mais rápido.

**MOG2 variance 1 → 100.** O limiar sobre a distância de Mahalanobis quadrática para um pixel
casar com seu modelo de fundo. Menor é mais sensível e mais ruidoso.

**Sombras.** As sombras detectadas são encontradas mas **nunca contadas** — uma sombra é o efeito
da coisa em movimento sobre o fundo, não a coisa em movimento. Desmarque para não gastar nada
procurando por elas.

### Fluxo óptico — Farneback e Lucas-Kanade

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Pyramid scale | `fb_pyr_scale` | float | 0,1 … 0,9 | `0.5` | Cada nível é essa fração do anterior |
| Pyramid levels | `fb_levels` | int | 1 … 8 | `3` | Mais níveis capturam movimento mais rápido |
| Window (px) | `fb_winsize` | int | 3 … 51 | `15` | Maior é mais suave e menos preciso |
| Iterations | `fb_iterations` | int | 1 … 10 | `3` | Passes de refinamento por nível |
| LK max points | `lk_max_points` | int | 1 … 1000 | `200` | Cantos rastreados por quadro |
| LK window (px) | `lk_win` | int | 3 … 51 | `15` | Também o tamanho do disco que cada ponto rastreado pinta |

!!! danger "O Farneback custa 30–60 ms por quadro a 640×512"

    Ele roda fora da thread da GUI, mas a reprodução vai pular quadros.

#### Análise de efeito

**Níveis da pirâmide 1 → 8.** O fluxo é estimado do grosseiro ao fino. Um nível só consegue
rastrear movimento menor que a janela; cada nível adicional aproximadamente dobra o deslocamento
rastreável, a um custo. Se objetos rápidos saem com fluxo zero, este é o controle.

**Janela 3 → 51.** A vizinhança sobre a qual cada vetor de fluxo é estimado. Janelas pequenas são
precisas e ruidosas e falham em regiões sem textura; janelas grandes são suaves, robustas e
borram a fronteira de movimento entre dois objetos que se movem de forma diferente.

**Escala da pirâmide 0,1 → 0,9.** Quanto cada nível encolhe. 0,5 reduz pela metade a cada vez — a
escolha convencional. Valores perto de 0,9 constroem muitos níveis quase idênticos, o que é lento
e ganha pouco; perto de 0,1 os níveis ficam tão distantes que a estimativa grosseira não guia bem
a fina.

**LK max points e window.** O Lucas-Kanade é *esparso* — ele rastreia cantos, então sua máscara é
um disco por ponto rastreado e não o contorno de coisa alguma. Use Farneback quando a forma da
coisa em movimento importa. A janela serve também de raio do disco, então aumentá-la produz uma
máscara de aparência mais suave e menos honesta.

### Mapa de calor

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Overlay the heatmap on the view | `heat_on` | bool | — | `false` | Compõe sobre qualquer visualização exibida |
| Opacity | `heat_opacity` | float | 0,0 … 1,0 | `0.5` | |
| Window (frames) | `heat_window` | int | 1 … 200 | `20` | Quão longe para trás o calor é promediado |
| Floor | `heat_threshold` | float | 0,0 … 1,0 | `0.05` | Fração da escala cheia abaixo da qual um pixel permanece frio |

`Motion heatmap` é uma média exponencial do movimento dos últimos N quadros, pintada com
`COLORMAP_JET` e **ponderada por pixel pelo próprio calor**, de modo que áreas frias permanecem
como o quadro em vez de lavarem de azul. Azul é movimento raro, vermelho é movimento constante.

#### Análise de efeito

**Janela 1 → 200.** Em 1 o mapa de calor é o movimento deste quadro e nada mais — ele pisca a
cada quadro. Em 200 é uma fotografia de longa exposição de onde houve movimento, assentando ao
longo de vários segundos e reagindo lentamente a mudanças. É uma média exponencial e não uma
janela de N quadros de verdade, então a cauda é suave em vez de um corte abrupto.

![Janela de calor de 3, 20 e 60 quadros sobre fluxo óptico denso](../assets/images/motion_heatmap.jpg)

**Piso 0,0 → 1,0.** Em 0 todo pixel recebe alguma cor, inclusive ruído puro, e o quadro fica
azul. Aumentá-lo mantém as partes frias da imagem como o quadro original, que é o que torna a
sobreposição legível.

### Objetos em movimento

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Min area (px) | `motion_min_area` | int | 0 … 5000 | `50` | Contornos menores que isso são ruído |
| Bounding boxes | `motion_boxes` | bool | — | `true` | |
| Label area and speed | `motion_metrics` | bool | — | `false` | Texto em cada caixa |
| Max travel (px/frame) | `motion_max_travel` | int | 1 … 500 | `60` | Além disso, dois blobs não são o mesmo objeto |

![Caixas, caixas com rótulos e o mapa de calor composto sobre a fonte](../assets/images/motion_boxes.jpg)

#### Análise de efeito

**Deslocamento máximo 1 → 500.** A velocidade é medida casando cada blob ao centroide mais
próximo do quadro anterior; este é o raio além do qual nenhum casamento é feito. Baixo demais e
objetos rápidos reportam velocidade zero por nunca terem sido casados; alto demais e blobs não
relacionados são pareados através do quadro e reportam absurdos.

!!! warning "Velocidade não é rastreamento"

    As caixas carregam área e velocidade em pixels por quadro, casadas pelo centroide mais
    próximo entre quadros. Isso responde *"quão rápido algo está se movendo aqui"*, **não** *"para
    onde foi o objeto 7"* — não existe identidade de trajetória, então dois blobs que se cruzam
    trocam de velocidade.

### As três regras de estado

O `MotionState` pertence a quem conduz os quadros — o worker tem o seu, uma exportação tem o dela
— e é reiniciado por três coisas, todas normais no uso cotidiano:

1. **O mesmo quadro duas vezes não o avança.** Arrastar um controle enquanto pausado reanalisa o
   quadro na tela repetidamente; alimentar um modelo de fundo com a mesma imagem cinquenta vezes
   ensina a ele que aquela imagem *é* o fundo, então um quadro parado desapareceria enquanto você
   ajusta. Os limiares continuam vivos, porém — só o estado carregado fica fixo.
2. **Uma busca ou um passo para trás o reinicia.** O quadro anterior não é mais o quadro
   anterior, e diferenciar através do salto acenderia a imagem inteira.
3. **Um modelo alterado o reinicia** — um algoritmo diferente, ou uma região redimensionada,
   deixa um modelo do tipo errado ou do formato errado.

A região não precisa de tratamento especial: o `adjust` recorta antes de qualquer recurso rodar,
então o quadro que este módulo vê *é* a região, e o mapa de calor fica confinado a ela de graça.

---

## Exportação

**Menu:** `File → Export analysis…` · **Atalho:** ++ctrl+s++

![O diálogo de exportação](../assets/images/dialog_export.png)

### O que faz

Roda a cadeia novamente sobre **todos os quadros** da fonte aberta com os ajustes atuais e grava
os resultados em uma pasta. Roda em sua própria thread com seu próprio estado de movimento, então
exportar enquanto a janela reproduz não atrapalha nem um nem outro.

### Como usar

1. Marque o que você quer.
2. Escolha uma pasta de saída — OK fica desabilitado até você ter as duas coisas.
3. Acompanhe o contador de quadros na barra de status.

| Opção | Valor do campo | Grava |
|---|---|---|
| Settings | `settings` | `settings.json` — o valor de cada controle, e nenhuma medida |
| CSV tables | `csv` | `metrics.csv` mais `contours.csv`, `keypoints.csv`, `blobs.csv`, `lines.csv`, `corners.csv`, `motion.csv`, `histogram.csv` |
| Overlays | `overlays` | `overlays/frame_%06d.png` — os quadros compostos |
| Objects | `objects` | `objects/frame_%06d_%02d.png` — cada objeto em movimento, recortado |

#### Por que os ajustes acompanham os números

Uma tabela de métricas sem os parâmetros que a produziram não é reprodutível, então os parâmetros
vão para a mesma pasta — e o arquivo tem o mesmo formato do cache do próprio aplicativo, então
++ctrl+l++ o lê de volta direto. Marcar **Settings** sozinho não lê quadro nenhum, então é
instantâneo.

O `metrics.csv` tem uma linha por quadro. Os CSVs por objeto têm uma linha por contorno,
keypoint, blob, linha, canto ou objeto em movimento, cada uma carregando o quadro de onde veio.
As linhas são **gravadas em fluxo, não acumuladas**: um clipe de 900 quadros com SIFT ligado
produz quase meio milhão de linhas de keypoints, que custariam mais memória do que o vídeo.

Os recortes de objeto saem do quadro **cru** e não do composto, então o que vai para o disco é o
objeto como a câmera o viu e não uma foto de uma caixa desenhada em volta dele.

!!! tip

    Com o HOG ligado, uma exportação custa cerca de um quarto de segundo por quadro. O diálogo
    avisa; não está travado.

---

## Dataset → Analyse

**Menu:** `Dataset → Analyse…` · **Atalho:** ++ctrl+d++ · **Precisa de:** `uv sync --group dataset`

![O diálogo de análise de dataset](../assets/images/dialog_analyse.png)

### O que faz

Todo o resto do aplicativo mostra o que os ajustes atuais *fazem*. Esta é uma das duas partes que
sabem o que eles *deveriam* fazer, porque é uma das duas com verdade de referência.

Ela recebe um dataset de segmentação COCO — um `instances_*.json` e a pasta de imagens que ele
descreve — e levanta **o que de fato separa os pixels anotados do seu fundo**. O COCO não precisa
de dependência extra: as anotações são JSON puro, os polígonos são `cv2.fillPoly`, e o RLE
decodifica em cerca de trinta linhas, incluindo a forma comprimida que a maioria das ferramentas
de exportação escreve.

### Como usar

1. Aponte para o arquivo de anotações. A pasta de imagens é adivinhada a partir dele — ao lado do
   JSON, ou em um irmão nomeado pelo split — e você pode corrigir o palpite.
2. Escolha uma pasta de saída.
3. Opcionalmente restrinja a uma classe pelo nome. Deixe em branco para todas; um nome errado é
   recusado com a lista dos válidos.
4. Defina quantas imagens decodificar para as métricas de pixel.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Annotations | `ann_path` | caminho | — | — | O `instances_*.json` |
| Images folder | `images_dir` | caminho | — | — | Onde vivem as imagens que ele nomeia |
| Output folder | `out_dir` | caminho | — | — | Cinco PNGs e um `summary.json` caem aqui |
| Images to sample | `n` | int | 1 … 100000 | `150` | Imagens decodificadas para as métricas de pixel |
| Class | `category` | texto | — | vazio | Vazio significa todas as classes |

### Duas passagens, e por quê

O levantamento roda em duas passagens porque elas custam três ordens de grandeza uma da outra.

- **Toda anotação do arquivo** é barata, então todas são usadas: razões de área, proporção,
  variância de escala, complexidade da máscara (`P²/4πA`), coocorrência de classes e sobreposição
  de caixas entre classes.
- **As métricas de pixel exigem imagens decodificadas**, então rodam sobre uma amostra:
  histogramas de cor em RGB/HSV/LAB, contraste, textura LBP, densidade de bordas Sobel e Canny,
  um perfil radial de FFT e um mapa de calor de ocupação.

Cada métrica de pixel é medida **duas vezes no mesmo quadro** — uma sob a máscara, outra sob o
complemento dela. Um histograma dos pixels anotados sozinho quase nada diz; a quantidade útil é a
*diferença* em relação ao fundo do qual eles precisam ser distinguidos, e tomar as duas do mesmo
quadro cancela exposição e conteúdo de cena da comparação.

#### Análise de efeito

**Imagens a amostrar 1 → 100000.** Só as métricas de pixel pagam por isso — as estatísticas de
anotação sempre cobrem o arquivo inteiro. Amostras pequenas são rápidas e ruidosas; algumas
centenas de imagens costumam bastar para os histogramas pararem de se mexer. O custo é linear:
cada imagem é decodificada uma vez.

**Filtro de classe.** Restringir a uma classe transforma "o que separa anotações do fundo" em "o
que separa *esta* classe de todo o resto, inclusive das outras classes", que costuma ser a
pergunta mais acionável.

### O que você recebe

Cinco figuras e um `summary.json`, abertos em um painel quando o trabalho termina.

| Figura | Mostra |
|---|---|
| `colour.png` | Histogramas RGB, HSV e LAB, máscara (contínuo) vs fundo (tracejado), normalizados por área |
| `texture.png` | Histograma LBP, densidade de bordas Sobel e Canny, contraste — máscara vs fundo |
| `spatial.png` | Mapa de calor de ocupação e perfil radial de frequência — onde estão os objetos e em quais frequências espaciais |
| `geometry.png` | Razão de área, proporção, variância de escala e complexidade de máscara por classe |
| `classes.png` | Coocorrência de classes e sobreposição de caixas entre classes |

![Cor: pixels anotados contra o próprio fundo, em três espaços](../assets/images/dataset_colour.png)

![Textura e bordas sob a máscara e sob o complemento dela](../assets/images/dataset_texture.png)

![Onde estão os objetos, e em quais frequências espaciais](../assets/images/dataset_spatial.png)

![Geometria por classe sobre todas as anotações do arquivo](../assets/images/dataset_geometry.png)

![Coocorrência de classes e sobreposição de caixas](../assets/images/dataset_classes.png)

!!! failure "Ele se recusa a produzir um relatório vazio"

    Se nenhuma imagem amostrada pôde ser medida, o trabalho levanta um erro em vez de gravar
    cinco figuras limpas, em branco e inteiramente convincentes. Nada em um gráfico em branco
    parece errado, que é exatamente o problema de produzir um.

---

## Dataset → Optimise

**Menu:** `Dataset → Optimise…` · **Atalho:** ++ctrl+shift+d++ · **Precisa de:** `uv sync --group dataset`

![O diálogo do otimizador](../assets/images/dialog_optimise.png)

### O que faz

Busca os ajustes que melhor reproduzem as máscaras de referência, usando um amostrador TPE do
Optuna sobre doze parâmetros e pontuando cada candidato contra as anotações reais do dataset.

### Como usar

1. Dê a ele os mesmos três caminhos que o levantamento pede.
2. Defina o número de tentativas e as imagens sobre as quais cada tentativa é pontuada.
3. Defina os três pesos do objetivo.
4. Rode. A tentativa zero é **o que estiver na tela**, então a busca parte do ajuste que você fez
   à mão e o resultado é sempre comparável a ele.
5. Ao terminar, escolha um compromisso da fronteira e pressione **Apply** — ou **Cancel** e fique
   com o que você tinha.

`Choose result…` no diálogo reabre o `front.json` de uma execução anterior e aplica um de seus
compromissos sem buscar de novo.

| Nome | Campo | Tipo | Faixa | Padrão | Descrição |
|---|---|---|---|---|---|
| Annotations / Images / Output | `ann_path`, `images_dir`, `out_dir` | caminho | — | — | Como acima |
| Images to sample | `n` | int | 1 … 100000 | `50` | Imagens sobre as quais **cada tentativa** é pontuada |
| Class | `category` | texto | — | vazio | |
| Trials | `trials` | int | 5 … 5000 | `100` | |
| α IoU | `weights[0]` | float | 0 … 100 | `1.0` | Sobreposição entre a máscara prevista e a verdadeira |
| β recall | `weights[1]` | float | 0 … 100 | `0.5` | Parcela da máscara verdadeira que foi encontrada |
| γ spill | `weights[2]` | float | 0 … 100 | `0.5` | Parcela do fundo incluída indevidamente |

### O objetivo

```
f(θ) = α·IoU(Mθ, Mgt) + β·|Mθ ∩ Mgt|/|Mgt| − γ·|Mθ \ Mgt|/|I \ Mgt|
```

Só a IoU bastaria para um benchmark. **β paga por cobertura**, de modo que um limiar tímido que
encontra uma fatia limpa de cada objeto não pode vencer. **γ cobra pelo fundo derramado**,
normalizado por quanto fundo existe, de modo que supersegmentar custa o mesmo com objetos grandes
ou pequenos.

A busca é genuinamente **multiobjetivo**: o Optuna maximiza IoU e recall e minimiza spill como
três direções separadas, e o que volta é uma fronteira de Pareto de compromissos não dominados em
vez de um único vencedor. O `f(θ)` acima é então usado para *ordenar* essa fronteira na exibição,
que é para o que servem os pesos.

!!! warning "γ precisa ser aumentado em objetos pequenos"

    Sua penalidade é dividida pelo fundo, e quando os objetos são ~1% do quadro o fundo é quase
    tudo — então uma máscara cobrindo dez vezes a referência é cobrada quase nada. No conjunto de
    pluma de exemplo, os pesos padrão pontuam uma máscara de 9,9% de cobertura em 0,5126 e uma
    justa de 1,6% em 0,5156: meio por cento de diferença para uma diferença de três vezes em IoU,
    o que é plano demais para o amostrador escalar. Com **γ = 5** a mesma busca devolve IoU 0,30
    em vez de 0,09.

    O resultado reporta IoU, recall, spill e cobertura separadamente exatamente por isso, e
    marca como **oversegmented** qualquer compromisso cuja máscara cubra mais de três vezes a
    referência.

### O que ele busca, e o que não busca

Doze parâmetros, e a razão é estrutural. `Mθ` é a `Contour mask`, e há um único caminho até ela:

```
adjust.apply() ─▶ canvases["Threshold"] ─▶ structure._contours() ─▶ "Contour mask"
```

| Buscado | Faixa |
|---|---|
| `brightness` | −100 … 100 |
| `contrast` | 0,5 … 3,0 |
| `saturation` | 0,0 … 3,0 |
| `gamma` | 0,3 … 3,0 |
| `color_space` | os cinco |
| `blur_kind` | os três |
| `blur` | 0 … 31 |
| `threshold_kind` | os seis |
| `threshold` | 0 … 255 |
| `adaptive_block` | 3 … 51 |
| `contour_mode` | os três |
| `contour_min_area` | 0 … 5000 |

HOG, LBP, SIFT, ORB, Canny, Hough, Harris e o detector de blobs **não conseguem mover a pontuação
em um pixel sequer**, porque produzem descritores, keypoints e sobreposições em vez de uma
máscara. Buscá-los não seria mais minucioso; seriam vinte e três dimensões de ruído a um segundo
por tentativa.

`contours_on` é fixado em **on**, já que é o que faz existir uma máscara, e `roi_on` fixado em
**off**, já que uma máscara de referência cobre o quadro inteiro.

Os floats propostos são arredondados para `0.01`, que é o que um slider consegue guardar. Caso
contrário o vencedor viraria silenciosamente um ajuste ligeiramente diferente no momento em que o
**Apply** o colocasse em um controle, e a pontuação impressa ao lado não seria a pontuação que
você tinha.

#### Análise de efeito

**Tentativas 5 → 5000.** O TPE precisa de talvez vinte tentativas antes de seu modelo superar a
amostragem aleatória, então qualquer coisa abaixo disso é efetivamente uma busca aleatória. O
custo é `tentativas × imagens` execuções completas da cadeia; as tentativas rodam em um pool de
processos com um núcleo deixado livre para a GUI.

**Imagens 1 … 100000.** Cada tentativa paga por isso, diferente de um levantamento. Amostras
pequenas tornam a pontuação ruidosa e o vencedor sobreajustado a um punhado de quadros; a amostra
é decodificada **uma vez** e mantida durante todo o estudo, então re-sorteá-la a cada tentativa
não pode tornar o objetivo estocástico.

### O que você recebe

![A fronteira de Pareto, ordenada por f(θ), com Apply](../assets/images/dialog_pareto.png)

O diálogo mostra cada compromisso não dominado com seu `f(θ)`, IoU, recall, spill, cobertura e os
ajustes que diferem da sua linha de base, e o cabeçalho informa a pontuação da linha de base para
que você veja se a busca superou o ajuste manual. Três arquivos caem na pasta de saída:

| Arquivo | Conteúdo |
|---|---|
| `best_settings.json` | O compromisso mais bem colocado, no mesmo formato que uma exportação grava — ++ctrl+l++ o lê de volta |
| `front.csv` | A fronteira, achatada para planilha |
| `front.json` | A fronteira inteira, que é o que o `Choose result…` reabre |

---

## Extração de ROS bag

**Menu:** `Rosbag → Extract from ROS bag…` · **Atalho:** ++ctrl+shift+e++ · **Precisa de:** `uv sync --group rosbag`

![O diálogo de ROS bag](../assets/images/dialog_rosbag.png)

### O que faz

Despeja em PNG ou JPG todas as mensagens de um tópico de imagem de um ROS 2 bag, para que uma
gravação vire uma pasta de quadros que este aplicativo — ou uma ferramenta de rotulagem — consiga
abrir.

Tem menu próprio em vez de ser um terceiro verbo de `Dataset`, porque um bag não é um dataset
COCO; é uma entrada *a partir da qual* um dataset COCO é construído.

### Como usar

1. Escolha um arquivo `.db3`. A lista de tópicos é lida do próprio arquivo, imediatamente, sem
   decodificar mensagem alguma — um `.db3` sozinho, sem `metadata.yaml` ao lado, lê normalmente.
2. Escolha o tópico de imagem. Se houver exatamente um, ele já vem selecionado.
3. Escolha uma pasta de saída e um formato.
4. Ao terminar, a confirmação oferece **Open folder**.

| Nome | Campo | Tipo | Valores | Padrão | Descrição |
|---|---|---|---|---|---|
| Bag | `bag_path` | caminho | `*.db3` | — | Um ROS 2 bag |
| Topic | `topic` | escolha | os tópicos de imagem do bag | o primeiro | Lido do arquivo |
| Output folder | `out_dir` | caminho | — | — | |
| Format | `fmt` | escolha | `png`, `jpg` | `png` | |

#### Análise de efeito

**Formato.** `png` é sem perdas e cerca de 5–10× maior; `jpg` tem perdas e é rápido. Se os quadros
vão virar dados de treinamento ou verdade de referência, use `png` — não dá para descomprimir um
artefato de JPEG depois, e limiarizar é exatamente a operação que transforma um artefato desses
em um contorno espúrio.

Tanto `sensor_msgs/msg/Image` quanto `sensor_msgs/msg/CompressedImage` são suportados, e cada
mensagem do tópico escolhido é gravada como um quadro.
