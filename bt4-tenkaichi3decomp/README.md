# Laboratório BT4 → Tenkaichi3Decomp

Ferramentas independentes para **analisar localmente** os arquivos do mod **Dragon Ball Z: Budokai Tenkaichi 4 Beta 13 Rev 5** e compará-los aos recursos extraídos de uma instalação original do [Tenkaichi3Decomp](https://github.com/z3xox/Tenkaichi3Decomp).

> **Estado:** diagnóstico inicial. **Não** é um port jogável, instalador, conversão automática ou sistema de patches MIPS para PC.

## Como executar no Windows

1. Tenha o Python 3 instalado.
2. Baixe do seu Google Drive a pasta do BT4, contendo `DATA/PZS4US0.AFS`, `DATA/PZS4US1.AFS` e `DATA/PZS4US2.AFS`.
3. Instale o Tenkaichi3Decomp utilizando sua cópia legítima da versão americana original de BT3 (SLUS-21678).
4. Execute a partir da pasta do projeto:

```powershell
python bt4_ferramenta.py analisar --bt4 "C:\Jogos\BT4\SLUS_219.78.DBZBT4B13ENGREV5" --bt3 "C:\Jogos\Tenkaichi3Decomp\gamedata" --saida "C:\Jogos\RelatorioBT4"
```

Serão criados `resumo.json` e `comparacao_afs.csv`. A ferramenta é somente leitura sobre os dados do jogo e não altera a instalação. Os relatórios podem conter informações sobre arquivos proprietários: revise antes de publicar.

Para extrair uma entrada individual, para análise **local**, use:

```powershell
python bt4_ferramenta.py extrair --afs "C:\Jogos\BT4\SLUS_219.78.DBZBT4B13ENGREV5\DATA\PZS4US1.AFS" --indice 42 --saida "C:\Jogos\Saida\recurso_00042.bin"
```

## Limites

- Uma correspondência de SHA-256 prova apenas identidade de bytes.
- Um índice AFS do BT4 pode representar outro recurso no BT3.
- O executável `SLUS_219.78` do BT4 é um ELF MIPS de PlayStation 2 e não pode ser instalado como executável de PC.
- Os AFS completos não foram transferidos do Drive para o ambiente de análise devido ao limite de tamanho; **nenhuma análise de seus conteúdos internos foi concluída**.
- Não publique ISOs, AFS, executáveis, texturas extraídas, músicas ou outros dados proprietários no repositório.

Código de referência: [extrator do Tenkaichi3Decomp](https://github.com/z3xox/Tenkaichi3Decomp/blob/main/port/tools/extract_disc.py) e [mecanismo de substituição de arquivos](https://github.com/z3xox/Tenkaichi3Decomp/blob/main/port/src/plat_file.c).

## Próximo passo

Executar a comparação local e examinar `resumo.json` e `comparacao_afs.csv` para identificar candidatos a adaptações individuais. Qualquer mod instalável exige validação adicional no port.
