# EPG_PT

Guia de programação (EPG) da NOS TV em formato [XMLTV](https://wiki.xmltv.org/index.php/XMLTVFormat), gerado a partir do guia público (modo "convidado", sem login) da API da NOS.

Atualizado automaticamente todos os dias por um [GitHub Action](.github/workflows/update-epg.yml), cobrindo hoje + amanhã.

## Usar no Dispatcharr (ou noutro player/PVR)

Adiciona como fonte EPG (tipo XMLTV) o URL "raw" deste ficheiro:

```
https://raw.githubusercontent.com/lbdd18/EPG_PT/main/guide.xml
```

## Correr manualmente

```bash
python3 update_epg.py
```

Não tem dependências fora da biblioteca standard do Python 3.9+.
