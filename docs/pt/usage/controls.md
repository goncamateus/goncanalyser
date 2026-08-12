# Controles de imagem e vídeo

Reprodução, avanço quadro a quadro, escala do visualizador, seleção de região, processamento em
lote de imagens e a referência completa de teclado e mouse.

## A barra de transporte

Tudo para percorrer uma fonte fica em uma linha só, sob a imagem.

![A janela, com a barra de transporte sob o visualizador](../assets/images/window_overview.png)

| Controle | O que faz |
|---|---|
| `View` | Qual etapa da cadeia aparece na tela. Dez opções — veja [Visão geral → As dez visualizações](overview.md#as-dez-visualizacoes) |
| ◀ | Volta um quadro. Pausa a reprodução |
| **Play** / **Pause** | Alterna a reprodução. O rótulo é a ação, não o estado |
| ▶ | Avança um quadro. Pausa a reprodução |
| Barra de busca | Pula para qualquer quadro. Vai de `0` a `quadros − 1` |
| Número do quadro | O índice exibido no momento |

### Reproduzir e pausar

++space++ alterna a reprodução de qualquer lugar da janela, e o botão também. A reprodução roda
na taxa de quadros da própria fonte quando a cadeia dá conta, e pula quadros quando não dá — HOG
e fluxo óptico denso são os dois que fazem ela não dar conta.

Enquanto pausado, **os controles continuam vivos**. Arrastar um controle reanalisa o quadro na
tela, então ajustar é, por projeto, uma atividade de pausa: você ganha a taxa de quadros do seu
próprio tempo de reação em vez da do vídeo. O worker pula a cadeia inteira quando está pausado em
um quadro que ninguém reajustou, então uma janela pausada não custa nada.

### Avançar quadro a quadro

++period++ avança, ++comma++ volta. Os dois pausam primeiro — avançar quadro a quadro enquanto
reproduz não é um pedido coerente, e o rótulo do botão acompanha.

!!! note "Voltar um quadro reinicia o estado de movimento"

    Regra 2 das [três regras de estado](features.md#as-tres-regras-de-estado): o quadro anterior
    não é mais o quadro anterior, então diferenciar através do salto acenderia a imagem inteira.
    Um modelo de fundo se reconstrói a partir da nova posição. Nada mais na cadeia é afetado — só
    o movimento carrega estado.

### Buscar na linha do tempo

A barra de busca cobre a fonte inteira. Arrastá-la emite uma busca por posição, e o worker pega a
mais recente — então arrastar rápido não enfileira trabalho. Como no passo para trás, uma busca
reinicia o estado de movimento.

A barra e o rótulo do quadro são atualizados *pelo* worker conforme ele avança, com os sinais
silenciados para que devolver a posição não seja lido como uma busca do usuário e não brigue com
o cursor que você está arrastando.

### Uma única imagem não tem transporte

Abra uma imagem e ◀, Play, ▶ e a barra se desabilitam sozinhos. Não há o que buscar, avançar ou
reproduzir, e deixá-los ativos seria manter quatro controles que não fazem nada. O seletor `View`
e todas as abas continuam funcionando normalmente.

## Escala do visualizador — e o que não existe aqui

O quadro é escalado para caber no visualizador com `KeepAspectRatio` e uma transformação suave, e
centralizado, então um dos eixos carrega uma faixa vazia. O visualizador tem tamanho mínimo de
640×360 e ocupa todo o espaço que a janela dá.

!!! warning "Não existe zoom nem pan"

    Esta é uma declaração deliberada de escopo, não uma omissão desta página. O visualizador
    encaixa o quadro na janela e é só isso que ele faz — não há controle de zoom, nem tratamento
    de roda do mouse, nem arrastar para deslocar, nem modo 1:1 de pixel.

    Duas coisas cumprem o papel para o qual as pessoas normalmente querem zoom:

    - **Redimensione a janela** (ou maximize). O quadro é reescalado a cada redimensionamento,
      então uma janela maior é uma imagem maior, com toda a suavização.
    - **Desenhe uma região.** Ela não amplia, mas restringe a análise à parte que interessa — que
      é justamente o que você ia ampliar para conferir — e ainda deixa os recursos caros uma
      ordem de grandeza mais rápidos enquanto isso.

    Se você precisa inspecionar pixels individuais, exporte as sobreposições e abra em um
    visualizador de imagens.

## Região de interesse

**Image Adjustment → Selection**, com duas formas intercambiáveis de definir o mesmo retângulo.

![Uma região: dentro dela é analisado, fora é o quadro cru](../assets/images/window_region.png)

### Desenhando com o mouse

1. Vá até a aba **Adjust** e pressione **Draw region on the image**.
2. O cursor sobre o visualizador vira uma cruz — o arraste agora está *armado*.
3. Arraste um retângulo sobre a imagem. Qualquer direção funciona; para cima e à esquerda é
   normalizado igual a para baixo e à direita.
4. Ao soltar, as quatro caixas numéricas se preenchem, **Limit analysis to a region** se marca
   sozinho, a barra de status informa `region x, y  w×h`, e o arraste é desarmado.

A seleção é **armada, não sempre ativa**. Um clique no visualizador seria, de outro modo,
indistinguível de um clique destinado a qualquer outra coisa, e um arraste acidental recortaria a
análise em silêncio sem ninguém perceber.

Um arraste que sai da borda do widget é limitado para dentro da imagem em vez de recusado — sair
pela borda é um "selecione até a margem" perfeitamente claro, e recusá-lo tornaria os cantos
difíceis de alcançar.

### Digitando

| Caixa | Campo | Passo | Significado |
|---|---|---|---|
| X | `roi_x` | 10 | Borda esquerda, px |
| Y | `roi_y` | 10 | Borda superior, px |
| W | `roi_w` | 10 | Largura. **`0` significa até a borda direita** |
| H | `roi_h` | 10 | Altura. **`0` significa até a borda inferior** |

As setas andam de 10 em 10 porque uma região é um número que você sabe ou empurra, não um que
você varre. As quatro são limitadas às dimensões da fonte, então não dá para digitar um retângulo
fora do quadro. **Reset to the full frame** zera as quatro sem mexer em nenhuma outra aba.

O mouse e as caixas ficam sincronizados — são duas interfaces para um retângulo, não dois
retângulos.

### Quando Draw fica indisponível

O botão se desabilita, com uma dica explicando o motivo, quando:

- a `View` é `Histogram` — aquilo é um gráfico de 512×256, não o quadro, e um retângulo desenhado
  sobre um gráfico não significaria nada; ou
- ainda não há fonte aberta.

Mudar para a visualização Histogram com um arraste armado o desarma.

## Processamento em lote de imagens

Uma pasta é uma fonte. Aponte o aplicativo para uma e cada imagem dentro dela vira um quadro:

```bash
uv run python main.py frames/
```

ou **File → Open image folder…** (++ctrl+shift+o++).

| Comportamento | Detalhe |
|---|---|
| Quais arquivos | Todo arquivo cuja extensão seja `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.webp` ou `.ppm` |
| Ordem | Ordenada por caminho, então `frame_001` … `frame_010` se comportam |
| Transporte | Totalmente vivo — Play percorre a pasta, ◀ ▶ avançam, a barra busca |
| Tamanho do quadro | As imagens podem ter tamanhos diferentes; cada uma é analisada como vem |
| Pasta vazia | Recusada com `no images in <caminho>` em vez de abrir em branco |

Duas coisas fazem disto o fluxo de lote e não apenas um visualizador:

1. **O ajuste vale para a pasta inteira.** Configure os controles uma vez, e cada imagem é
   analisada com os mesmos ajustes — que é o sentido de um lote.
2. **A exportação roda a fonte inteira de novo.** ++ctrl+s++ grava uma linha de `metrics.csv` por
   imagem, linhas por objeto carregando o índice do quadro de onde vieram e — se marcado — um PNG
   de sobreposição por imagem. O `metrics.csv` também carrega o **nome do arquivo** de cada
   quadro, então uma linha pode ser rastreada até a imagem de origem.

!!! tip "Trocar a fonte preserva o seu ajuste"

    Abrir outro arquivo ou outra pasta **não** reinicia os controles. O ajuste é a coisa que você
    leva de uma imagem para a próxima, então uma nova fonte reaproveita a janela em vez de abrir
    uma segunda.

## Controles de trabalhos de dataset

Um levantamento de dataset, uma otimização ou uma extração de bag roda em sua própria thread atrás
de uma janela **não modal** — você pode continuar trabalhando enquanto ela roda.

| Controle | O que faz |
|---|---|
| **Hide** | Guarda a janela e **deixa o trabalho rodando** |
| **Cancel** | Para o trabalho. Cooperativo, então tem efeito ao fim do passo em andamento — uma tentativa, ou uma imagem |
| A pizza na barra de status | Mostra o progresso enquanto o trabalho durar. **Clique nela para trazer a janela de volta** |

Os dois botões soam parecidos e não são. Esconder não pode perder de vista um trabalho de dez
minutos, porque a pizza fica no canto e clicar nela reabre a janela.

As mensagens do trabalho vão para um rótulo próprio ao lado da pizza em vez de compartilhar o
`showMessage` com o worker de quadros — que escreve ali a cada quadro, cem por segundo mesmo
pausado, e apagaria qualquer coisa que o trabalho tivesse a dizer antes de poder ser lida.

Fechar o aplicativo cancela um trabalho em andamento em vez de esperar por ele.

## Referência de teclado

!!! info "macOS"

    O Qt mapeia ++ctrl++ de um atalho para ++cmd++, então todo `Ctrl+…` abaixo é `⌘…` no macOS.
    Essa é a grafia portátil, não um vício do Windows.

### Transporte

| Teclas | Ação |
|---|---|
| ++space++ | Reproduzir / pausar |
| ++period++ | Avançar um quadro |
| ++comma++ | Voltar um quadro |

### Arquivo

| Teclas | Ação |
|---|---|
| ++ctrl+o++ | Open image or video… |
| ++ctrl+shift+o++ | Open image folder… |
| ++ctrl+l++ | Load settings… |
| ++ctrl+s++ | Export analysis… |
| ++ctrl+r++ | Reset all controls — pressione de novo para desfazer |
| ++ctrl+comma++ | Preferences… |
| ++ctrl+w++ | Fechar janela |
| ++ctrl+q++ | Sair |

### Dataset e bags

| Teclas | Ação |
|---|---|
| ++ctrl+d++ | Dataset → Analyse… |
| ++ctrl+shift+d++ | Dataset → Optimise… |
| ++ctrl+shift+e++ | Rosbag → Extract from ROS bag… |

### O reset também é uma comparação A/B

++ctrl+r++ não pede confirmação — um atalho que para para perguntar não vale a pena. Em vez disso
ele guarda os valores anteriores, então um ++ctrl+r++ digitado por engano custa mais uma tecla em
vez dos últimos vinte minutos de ajuste. Pressione de novo e seu ajuste volta, e ele continua
alternando entre os padrões e os seus últimos valores.

Isso faz dele o jeito mais rápido de responder "isto é de fato melhor que o padrão?".

## Referência de mouse

| Ação | Onde | Resultado |
|---|---|---|
| Arrastar com o botão esquerdo | Sobre a imagem, **depois** de pressionar Draw | Seleciona uma região. Desarma em seguida |
| Clique esquerdo | A pizza de progresso na barra de status | Reabre a janela escondida de um trabalho de dataset |
| Rolagem | Uma aba de controles | Rola apenas aquela aba — cada uma tem sua própria área de rolagem |
| Clique esquerdo | Uma entrada de análise na barra de menus | Levanta aquela aba. Nunca abre uma segunda janela |
| Arrastar | A barra de busca | Percorre a fonte |

Todo o resto é controle Qt padrão: sliders arrastam e aceitam as setas, caixas numéricas aceitam
digitação e passos, combos abrem com ++space++ ou com um clique.

## Menus em resumo

| Menu | Entradas |
|---|---|
| `File` | Open image or video…, Open image folder…, Load settings…, Export analysis…, Reset all controls, Preferences…, Close window, Quit |
| `Image Adjustment` · `Global` · `Local` · `Structures` · `Motion` | Cada um levanta sua aba |
| `Dataset` | Analyse…, Optimise… |
| `Rosbag` | Extract from ROS bag… |

![Preferences: onde vive o cache de ajustes, e um reset](../assets/images/dialog_preferences.png)

**File → Preferences** mostra o caminho do cache de ajustes —
`~/.config/analyser/settings.json` no Linux, `~/Library/Preferences/analyser/settings.json` no
macOS — e oferece o mesmo reset que o ++ctrl+r++.
