# BT Mod Manager — Protótipo 0.1

Instalador **local**, gratuito e de código aberto para **Tenkaichi3Decomp**, desenvolvido como laboratório de conversão de mods de PS2 (incluindo o BT4). Não distribui o jogo nem ativos proprietários.

## Recursos

- Interface para Windows (`abrir_instalador.bat`) sem dependências externas além do Python 3 com Tkinter.
- Importa pastas, arquivos ZIP, AFS e ISO 9660 de PS2 diretamente. Para RAR/7z, extraia primeiro.
- Inspeciona entradas dentro de AFS sem extrair o arquivo inteiro, inclusive AFS localizados em ISO.
- Comparação SHA-256 com arquivos do BT3 original, quando existe o mesmo índice; lista os recursos alterados, idênticos e desconhecidos.
- Adiciona texturas (`textures/`), músicas (`songs/`), cenários (`stages/`) e recursos indexados (`gamedata/mods/`).
- Identifica `ZS4USOP.ADX` e `ZS4USED.ADX` e propõe adicioná-los como músicas extras. Os vídeos `ZS4USOP.PSS` e `ZS4USED.PSS` são sinalizados como **experimentais**.
- Visualização das alterações, seleção individual, exportação CSV de **todas** as entradas, SHA-256 e histórico de instalação.
- Backups de overrides existentes e desfazer instalações verificando integridade antes de restaurar.

## Iniciar no Windows

1. Instale [Python 3 para Windows](https://www.python.org/downloads/windows/).
2. Instale o [Tenkaichi3Decomp](https://github.com/z3xox/Tenkaichi3Decomp/releases) usando **sua própria cópia legítima do BT3 original americano (SLUS-21678)**.
3. Extraia o pacote deste projeto e dê duplo clique em `abrir_instalador.bat`.
4. Indique a pasta do jogo que contém `gamedata`, depois selecione a ISO, AFS, ZIP ou pasta do mod.
5. Clique em **1. Analisar mod**. Inspecione as mudanças. As alterações experimentais não são pré-selecionadas.
6. Marque os arquivos que deseja aplicar; clique em **2. Instalar selecionados**.
7. Para desfazer, use **Ver histórico / desfazer**.

Os arquivos originais em `gamedata/pzs3us0`, `gamedata/pzs3us1` e `gamedata/pzs3us2` **nunca são sobrescritos**: as substituições ficam sob `gamedata/mods/`. Outros arquivos somente podem ser escritos em `textures/`, `songs/` e `stages/`. Backups e journal ficam em `.bt_mod_manager/history/`, dentro da pasta do jogo.

## Linha de comando (opcional)

```powershell
py -3 mod_installer.py scan --mod "C:\Jogos\BT4\SLUS_219.78.DBZBT4B13ENGREV5" --game "C:\Jogos\Tenkaichi3Decomp" --csv "C:\Jogos\relatorio.csv"
py -3 mod_installer.py install-safe --mod "C:\Jogos\BT4\SLUS_219.78.DBZBT4B13ENGREV5" --game "C:\Jogos\Tenkaichi3Decomp"
py -3 mod_installer.py undo --game "C:\Jogos\Tenkaichi3Decomp" --id "ID_DO_HISTORICO"
```

O comando `install-safe` instala **apenas** arquivos classificados como diretos; não instala sobreposições AFS classificadas como experimentais.

## Limitações técnicas honestas

- **Não é um conversor universal.** Mods com novos personagens, endereços de memória, patch de código MIPS, novas lógicas, transformações ou mudanças no `SLUS_219.78` precisam de adaptação de código. O instalador informa esses arquivos como não reconhecidos.
- Um arquivo com o mesmo índice em um AFS de BT4 e BT3 pode representar recursos diferentes. **O mapeamento é experimental e deve ser testado individualmente.** Não selecione milhares de entradas de uma vez.
- `PZS4US*.AFS` não deve ser copiado para `pzs3us*` inteiro. O instalador compara entradas individuais e propõe arquivos `gamedata/mods/pzs3us*/NNNNN.bin`.
- A comparação com o BT3 somente identifica bytes iguais ou diferentes nos índices verificados. Ela **não permite inferir com certeza quais mecânicas ou personagens foram alterados**. Para uma análise semântica completa, serão necessárias ferramentas de interpretação dos formatos do jogo.
- Não faz merge automático de `songs.txt` nem gera listas `maps.txt` para cenários; acrescenta os arquivos compatíveis, que podem ser detectados automaticamente pela versão atual do port. Nomes customizados e ordens exigem listas manuais.
- A visualização limita-se a 3.000 linhas por filtro por razões de desempenho. O CSV exportado contém todas as entradas identificadas.
- AFS dentro de ZIP deve ser extraído para uma pasta antes da análise. O formato ISO é lido em modo ISO9660 convencional, sem suporte a variantes comprimidas ou UDF.
- Não há executável `.exe` independente nesta versão. `abrir_instalador.bat` utiliza Python 3 instalado. Sem suporte ainda a instalações e remoções concorrentes.
- Alterações em `PSS` podem falhar porque o decodificador atual do port tem requisitos específicos. Músicas não garantem compatibilidade com o vídeo original.

## Testes

Execute `py -3 -m unittest -v test_installer.py`. Testes abrangem ZIP, ISO simulado, AFS, backups, rollback, arquivos reais de áudio ADX e proteção contra caminhos inseguros. Não houve execução dentro do jogo, portanto a compatibilidade in-game do BT4 ainda deve ser validada.

Código oficial: https://github.com/z3xox/Tenkaichi3Decomp

**Direitos autorais:** não publique ISOs, arquivos AFS, executáveis de jogos, músicas, modelos extraídos nem ativos de terceiros no GitHub. Esta ferramenta deve ser utilizada com cópias autorizadas.