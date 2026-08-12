# goncanalyser

**Um espaço de trabalho Qt para ver o que o OpenCV vê.**

Carregue uma imagem, uma pasta ou um vídeo; empilhe o pré-processamento; ligue extratores de
cor, textura, keypoints, estruturas ou movimento; acompanhe o resultado na velocidade de
reprodução; exporte os números.

![A janela: visualizador à esquerda, controles à direita, transporte embaixo](assets/images/window_overview.png)

## Para que serve

Todo parâmetro do OpenCV é só um número dentro de um script até você conseguir ver o que ele
faz. O `goncanalyser` coloca a cadeia inteira atrás de controles ao vivo e de uma imagem, de
modo que ajustar um limiar vira um slider em vez de um ciclo editar-executar-olhar. Um quadro
percorre a cadeia uma única vez, e essa execução única alimenta o visualizador, a barra de
status e a exportação — o que você vê é o que é medido.

Ele foi feito para três tarefas:

- **Escolher um operador.** Seis algoritmos de movimento, dois detectores de keypoints, quatro
  operadores de borda e cinco modos de limiar, todos alcançáveis sem alterar uma linha de
  código, todos medindo o mesmo quadro.
- **Ajustar o operador que você já escolheu.** Todos os controles ficam na tela enquanto o
  vídeo roda, e os números da barra de status acompanham.
- **Comprovar o ajuste contra a verdade de referência.** Aponte o menu **Dataset** para um
  conjunto de segmentação COCO e ele levanta o que de fato separa os pixels anotados do fundo
  — ou busca os ajustes que melhor reproduzem as máscaras.

O público é qualquer pessoa que precise justificar um parâmetro: engenheiros de visão
computacional, estudantes montando um primeiro pipeline e quem tem um dataset rotulado e um
limiar escolhido porque *parecia* razoável.

## Principais recursos

:material-tune: **Pré-processamento ao vivo** — brilho, contraste, saturação, gama, espaço de
cor, dois desfoques e cinco modos de limiar, aplicados *antes* de todos os outros recursos,
para que todos meçam o quadro que você moldou.

:material-palette: **Cor** — histogramas RGB, HSV e LAB, sempre medidos, desenhados no painel e
exportados por bin.

:material-texture-box: **Textura** — HOG e LBP, com entropia na barra de status.

:material-vector-point: **Keypoints** — SIFT e ORB atrás de um único controle de sensibilidade
normalizado, de modo que "mais keypoints" é o mesmo gesto para os dois.

:material-vector-square: **Estruturas** — bordas Canny, Sobel e Laplaciano, linhas e círculos
de Hough, cantos Harris e Shi-Tomasi, contornos e blobs.

:material-run-fast: **Movimento** — seis algoritmos, uma sensibilidade compartilhada, um mapa
de calor exponencial e área e velocidade por objeto.

:material-crop: **Região de interesse** — arraste um retângulo e tudo fora dele fica de fora
dos números *por construção*, não por convenção.

:material-file-export: **Exportação** — `settings.json` junto de `metrics.csv` e um CSV por
tipo de objeto, além dos quadros compostos e dos objetos recortados. As linhas são gravadas em
fluxo, então um clipe de 900 quadros com SIFT ligado não vira um problema de memória.

:material-database-search: **Ferramentas de dataset** — levante um conjunto COCO, ou rode uma
busca multiobjetivo com Optuna pelos ajustes que reproduzem suas máscaras, e aplique o
resultado ao painel com um clique.

:material-package-variant-closed: **Distribuído como aplicativo de desktop** — AppImage para
Linux e um dmg para macOS, construídos pela CI a cada tag.

## Por onde seguir

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } **Instalação**

    ---

    Execute a partir do código-fonte com `uv`, ou pegue um AppImage ou dmg pronto. Inclui como
    construir seu próprio instalador nas três plataformas.

    [:octicons-arrow-right-24: Instalar](installation.md)

-   :material-map:{ .lg .middle } **Visão geral**

    ---

    Como a cadeia se encaixa, o que cada uma das dez visualizações mostra e por que uma
    sobreposição combina com qualquer uma delas.

    [:octicons-arrow-right-24: Entender](usage/overview.md)

-   :material-tune-vertical:{ .lg .middle } **Recursos**

    ---

    Cada recurso, cada parâmetro, o que mudar do mínimo ao máximo realmente faz, com uma figura
    para cada um.

    [:octicons-arrow-right-24: Ajustar](usage/features.md)

-   :material-keyboard:{ .lg .middle } **Controles**

    ---

    Reprodução, avanço quadro a quadro, seleção de região, processamento em lote e a referência
    completa de teclado e mouse.

    [:octicons-arrow-right-24: Operar](usage/controls.md)

-   :material-github:{ .lg .middle } **Código-fonte**

    ---

    O repositório, os lançamentos e o rastreador de issues.

    [:octicons-arrow-right-24: github.com/goncamateus/goncanalyser](https://github.com/goncamateus/goncanalyser)

</div>

## Em um comando

```bash
uv sync
uv run python main.py clip.mp4
```

Sem argumento a janela abre vazia; `File → Open` (++ctrl+o++) responde a isso. Um caminho de
pasta também funciona, e é assim que se processa um diretório de imagens em lote.

!!! info "Sobre as figuras desta documentação"

    Toda captura de tela e toda tira comparativa deste site foram geradas por
    [`docs/make_assets.py`](https://github.com/goncamateus/goncanalyser/blob/main/docs/make_assets.py)
    a partir do aplicativo real e de um clipe térmico real — sem maquetes, sem ilustrações.
    Rode você mesmo com `uv run --group dataset python docs/make_assets.py`.
