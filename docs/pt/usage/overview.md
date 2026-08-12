# Visão geral

Como a janela é organizada, o que roda em qual ordem e o que cada visualização está mostrando.

## A janela

![Visualizador à esquerda, cinco abas de controle à direita, transporte embaixo](../assets/images/window_overview.png)

Visualizador à **esquerda**, controles à **direita** em cinco abas, barra de transporte abaixo
da imagem, barra de status na base.

As entradas `Image Adjustment | Global | Local | Structures | Motion` da barra de menus
**levantam a aba correspondente** em vez de abrir uma segunda janela. Existe exatamente uma
definição de cada controle, ela está sempre a um clique de distância e nunca cobre a imagem.
`File`, `Dataset` e `Rosbag` são os menus que abrem diálogos, porque abrir, exportar e rodar um
trabalho são perguntas de uma resposta só — você responde uma vez e a resposta é executada.

O painel tem 400 px fixos de largura e cada aba rola de forma independente.

| Região | O que fica ali |
|---|---|
| Barra de menus | `File`, as cinco entradas que levantam abas, `Dataset`, `Rosbag` |
| Visualizador | O quadro composto, escalado para caber. Também é onde a região é arrastada |
| Barra de transporte | Seletor `View`, ◀ voltar, Play/Pause, ▶ avançar, barra de busca, número do quadro |
| Abas de controle | Adjust, Global, Local, Structures, Motion |
| Barra de status | Fonte, índice do quadro, tamanho do quadro, métricas ao vivo, estado de reprodução — mais a pizza de progresso à direita enquanto um trabalho de dataset roda |

## A cadeia

Um quadro percorre a cadeia uma única vez. Essa execução alimenta o visualizador, a barra de
status e a exportação, então nada é calculado duas vezes e nada ganha um segundo caminho de
código.

```
adjust ──▶ motion ──▶ structure ──▶ keypoints ──▶ texture ──▶ colour
```

`adjust` roda primeiro e à parte, porque produz o quadro que todos os outros recursos leem.
`motion` vem em seguida para que sua sobreposição fique *embaixo* das dos detectores — um mapa
de calor pintado por último enterraria todas as caixas desenhadas antes. `colour` é o último
apenas por ser o único recurso que lê o quadro e não desenha nada nele.

Cada recurso escreve em três coletores:

| Coletor | O que guarda | Onde aparece |
|---|---|---|
| **canvases** | Imagens de quadro inteiro que o recurso pode oferecer como *a* visualização | O seletor `View` |
| **ops** | Funções que pintam geometria sobre a tela escolhida | Sobreposições |
| **metrics** | Escalares por quadro | A barra de status e o `metrics.csv` |
| **rows** | Registros por objeto — um por contorno, keypoint, blob, linha ou canto | Os CSVs por objeto |

Separar `ops` de `canvases` é o que permite que **qualquer sobreposição combine com qualquer
visualização** sem que nenhum dos dois recursos saiba que o outro existe. "Canny com keypoints
SIFT por cima" são dois controles, não um caso especial.

!!! tip "Adicionar um recurso"

    Um módulo com `run(frame, settings, out, state=None)` e uma aba que declara seus controles.
    Nada mais muda — nem a janela, nem o worker.

## As dez visualizações

`View`, sob a imagem, decide qual etapa aparece na tela. As sobreposições de geometria são
desenhadas *por cima* da que você escolheu.

| Visualização | Produzida por | Observações |
|---|---|---|
| `Source` | Image Adjustment | O quadro pré-processado. **Se um modo de limiar estiver selecionado, ele é binário** — limiarizar faz parte do pré-processamento |
| `Grayscale` | Image Adjustment | Canal único do quadro pré-processado, como BGR |
| `Threshold` | Image Adjustment | O que o localizador de contornos lê. Derivado em Binary/`Level` mesmo quando o combo de limiar diz `None` |
| `Edges` | Structures | Canny, Sobel ou Laplaciano |
| `Contour mask` | Structures | Contornos preenchidos — a máscara que o otimizador pontua |
| `Motion mask` | Motion | O primeiro plano extraído |
| `Motion heatmap` | Motion | Média exponencial do movimento, `COLORMAP_JET`, ponderada por pixel pelo próprio calor |
| `HOG` | Global | A visualização de orientação de gradiente |
| `LBP` | Global | A imagem de códigos do padrão binário local |
| `Histogram` | Global | Um gráfico de 512×256, não um quadro — a única visualização em que não se pode desenhar uma região |

Uma visualização cujo recurso está desligado nunca é produzida, e o visualizador **volta para
`Source`** em vez de ficar em branco. Manter uma visualização cujo recurso você acabou de
desligar é normal, e apagar a imagem por isso seria pior do que mostrar a fonte.

## Pré-processamento não é cosmético

A aba Image Adjustment roda *antes* de todo o resto, espaço de cor incluído. Bordas, keypoints
e textura medem o quadro que ela produz, então mudar para LAB realmente muda o que o SIFT vê.
Esse é o objetivo, não um efeito colateral.

Duas consequências que vale ter em mente desde o começo:

- **Contornos leem a imagem `Threshold`, não o mapa de bordas.** Encontrar contornos exige uma
  imagem binária, e limiarizar é como se obtém uma. Ajuste o limiar primeiro e use a
  visualização `Threshold` para ver exatamente o que está sendo entregue ao localizador.
- **Selecionar um modo de limiar binariza o próprio quadro de trabalho**, então a visualização
  `Source` também fica em preto e branco e todo recurso a jusante mede uma imagem binária.
  Deixe o combo em `None` e a tela `Threshold` continua sendo derivada para o localizador de
  contornos — que é como se obtêm caixas de contorno desenhadas sobre um quadro colorido.

## Região de interesse

**Image Adjustment → Selection** limita toda a análise a um retângulo.

![Região ligada: dentro é limiarizado por Otsu, fora é o quadro decodificado cru](../assets/images/window_region.png)

A moldura ao redor do retângulo permanece na tela como contexto e **nunca chega aos números**.
Essa garantia é o motivo de o recorte acontecer *primeiro* na cadeia e não por último, o que
teria sido mais fácil de ligar: o `Otsu` escolhe seu nível a partir do histograma que recebe, e
um desfoque lê a vizinhança de um kernel além da borda, então recortar depois deixaria o
entorno definir o limiar e vazar pela margem. O fundo que você vê é o quadro decodificado cru,
nunca processado, então ele não pode vazar por construção.

A autoverificação do `core.pipeline` fixa isso: ela analisa uma região, zera todos os pixels
fora dela, reanalisa e afirma que as métricas são idênticas byte a byte — com Otsu e um
desfoque ligados, porque são os dois operadores que vazam.

As coordenadas exportadas são traduzidas de volta para pixels do quadro inteiro, então um CSV
significa a mesma coisa com região e sem região.

É também o jeito barato de tornar utilizáveis os recursos caros: SIFT + HOG sobre um quadro
completo de 640×512 custa **202 ms**; sobre uma região de 200×160, **21 ms**.

Veja [Controles → Região de interesse](controls.md#regiao-de-interesse) para saber como
desenhar uma.

## Threads e responsividade

| Thread | O que faz |
|---|---|
| GUI | Widgets, e montar um `Settings` quando um controle se move |
| `Worker` | Decodifica quadros e roda a cadeia. Um por fonte aberta |
| `ReportThread` | Uma exportação. Roda a cadeia sobre todos os quadros |
| `DatasetThread` | Um trabalho de dataset — levantamento, busca ou extração de bag |

`Settings` é uma dataclass congelada. A thread da GUI nunca altera aquela que o worker está
lendo: ela monta uma inteiramente nova e reassocia um único atributo, o que é atômico no
CPython. O worker portanto sempre vê um conjunto de valores autoconsistente, e nenhum dos lados
precisa de lock.

Duas coisas mantêm a taxa de quadros:

- O worker **pula a cadeia inteira** quando está pausado em um quadro que ninguém reajustou.
- Uma tela só é **convertida em miniatura QImage quando a aba que a mostra está visível** — as
  prévias dos painéis Global e Motion não custam nada enquanto você está em outra aba.

### Custo medido por quadro a 640×512

| Recurso | Custo | Consequência |
|---|---|---|
| HOG | 150–300 ms | Mais lento do que um quadro de vídeo chega. Desligado por padrão; a reprodução pula quadros enquanto ele está ligado |
| Fluxo denso Farneback | 30–60 ms | Perceptível mas utilizável |
| Os outros cinco algoritmos de movimento | ~8 ms | Confortavelmente em tempo real |
| Todo o resto | ~8 ms ou menos | Confortavelmente em tempo real |

## Ajustes, salvos e restaurados

**Gravados ao sair, restaurados na próxima execução**, no diretório de configuração por
plataforma que o Qt indica:

| Plataforma | Caminho |
|---|---|
| Linux | `~/.config/analyser/settings.json` |
| macOS | `~/Library/Preferences/analyser/settings.json` |

Um arquivo ausente ou corrompido é ignorado em vez de fatal, e um cache gravado antes de um
controle existir ainda carrega — o campo ausente mantém seu padrão. **File → Preferences**
mostra o caminho e oferece um reset.

**File → Load settings…** (++ctrl+l++) faz o caminho inverso: aponte para um `settings.json`
exportado e o ajuste que produziu aquela exportação volta para os controles. Reproduzir uma
execução é justamente o motivo de exportar os ajustes junto das métricas. O arquivo de cache
também funciona ali — o mesmo dicionário plano, só que não aninhado sob `settings` — e, de
qualquer forma, um campo que o arquivo não carrega mantém o valor atual, então uma exportação de
uma versão antiga ainda carrega.

**File → Reset all controls** (++ctrl+r++) não pede confirmação — um atalho que para para
perguntar não vale a pena. Em vez disso ele guarda os valores anteriores, então pressioná-lo de
novo os devolve, e ele continua alternando entre os padrões e o seu último ajuste. Isso serve de
comparação A/B.

## Exportação em um parágrafo

**File → Export analysis…** (++ctrl+s++) roda a cadeia novamente sobre todos os quadros e grava
qualquer combinação de `settings.json`, sete CSVs, PNGs compostos e cada objeto em movimento
recortado do quadro *cru*. As linhas são gravadas em fluxo e não acumuladas — um clipe de 900
quadros com SIFT ligado produz quase meio milhão de linhas de keypoints, que custariam mais
memória do que o vídeo. O detalhamento completo está em
[Recursos → Exportação](features.md#exportacao).

## De onde vêm os números

A barra de status carrega a fonte, o índice do quadro, o tamanho do quadro e todas as métricas
por quadro que os recursos ligados produziram — `B_mean`, `R_sd`, `contours`, `keypoints`,
`motion_objects`, `motion_speed`, `lbp_entropy` e assim por diante. É o mesmo dicionário
`metrics` que vira uma linha do `metrics.csv`, então o que você lê enquanto ajusta é exatamente
o que uma exportação registra.
