# Primeiro prototipo BT4: audio de abertura e encerramento como BGM adicional

**Estado:** ferramenta de instalacao testada em arquivos ADX reais da Beta 13 Rev 5 e em uma pasta de instalacao simulada. **A reproducao dentro do jogo ainda precisa de teste no PC do usuario.**

O objetivo deste teste inicial e aproveitar os arquivos de audio **ZS4USOP.ADX** (abertura) e **ZS4USED.ADX** (encerramento) que ja estao separados no diretorio DATA do BT4, sem extrair os tres arquivos AFS.

O port oficial [suporta adicionar ADX ao seletor de musicas](https://github.com/z3xox/Tenkaichi3Decomp/blob/main/docs/port/adding_songs.md). Os arquivos foram inspecionados: o primeiro e ADX 48 kHz estereo; o segundo e ADX 24 kHz estereo. O codigo de instalacao verifica os cabecalhos e se recusa a sobrescrever uma copia diferente.

## O que faz
- Copia localmente DATA/ZS4USOP.ADX para songs/BT4_Abertura.adx;
- Copia DATA/ZS4USED.ADX para songs/BT4_Encerramento.adx;
- Adiciona ambas as faixas a songs/songs.txt, sem duplicar as linhas ao executar novamente;
- Nunca modifica as pastas gamedata e DATA originais.

**Importante:** nao troca a abertura da tela inicial nem os videos cinematograficos. Apenas permite escolher esses audios como musica de batalha; nessa situacao, as musicas sao repetidas em loop.

## Uso no Windows
1. Instale Python 3.
2. Instale o Tenkaichi3Decomp com uma copia legitima do BT3 USA original, sem modificacoes, usando o instalador oficial.
3. Baixe do proprio Google Drive os arquivos do BT4. Garanta que os dois .ADX estejam na pasta DATA do BT4.
4. Coloque instalar_audio_bt4.py em um local do computador e abra PowerShell nesse local.
5. Simule primeiro:

~~~powershell
py -3 .\instalar_audio_bt4.py --bt4 "C:\Jogos\BT4\SLUS_219.78.DBZBT4B13ENGREV5" --port "C:\Jogos\Tenkaichi3Decomp" --dry-run
~~~

6. Se tudo estiver certo, execute sem --dry-run:

~~~powershell
py -3 .\instalar_audio_bt4.py --bt4 "C:\Jogos\BT4\SLUS_219.78.DBZBT4B13ENGREV5" --port "C:\Jogos\Tenkaichi3Decomp"
~~~

7. Abra o jogo e entre na selecao de musica de batalha. Procure "BT4 Abertura" e "BT4 Encerramento".

Se instalou Tenkaichi3Decomp em outro lugar, ajuste --port. O mesmo vale para a pasta BT4 em --bt4.

## Como remover manualmente
Com o jogo fechado, remova os arquivos **songs/BT4_Abertura.adx** e **songs/BT4_Encerramento.adx**. Abra **songs/songs.txt** e remova somente as duas linhas com esses nomes (deixe as demais intactas).

## Limites e direitos
Nao inclui nem redistribui musicas, ISOs ou dados do jogo. Utilize arquivos da sua propria copia autorizada. O suporte de ADX permite um teste inicial, nao garante compatibilidade de personagens, menus, modo historia e cinematics.
