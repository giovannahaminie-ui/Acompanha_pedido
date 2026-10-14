"""
Monta (e NÃO envia) o envelope GravarOrdensCompra_5 que o Acompanha_pedido
manda ao gerar a OC - mesmos parâmetros de db/pedido_ws.py::gerar_ordem_compra.

Só baixa o WSDL (pra validar a estrutura) e usa zeep.create_message; nenhuma
chamada é feita ao serviço, então nenhuma OC é gerada.

Uso:  python teste_envelope_oc.py
"""
import os
import re
from pathlib import Path

import zeep
from dotenv import load_dotenv
from lxml import etree

load_dotenv(Path(__file__).parent / ".env")

WSDL = os.environ["OC_WS_WSDL"]
USER = os.environ.get("OC_WS_USER", "usuario")

# --- valores de teste (ajuste à vontade) ---------------------------------
CODEMP, CODFIL, COD_FOR, CODDEP = 1, 1, 3, "1"
ITENS = [{"codpro": "50015801", "qtd": 1.0, "preco": 16.27}]
OBS_OCP = "OS 129855 - Solicitação 165486 - Pedido 792657 - Solicitante: rafaela.hirota"
# --------------------------------------------------------------------------

parameters = {
    "tipoProcessamento": 1,
    "identificadorSistema": "INTEGRADO",
    "fechaOC": "1",
    "dadosGerais": [{
        "codEmp": CODEMP,
        "codFil": CODFIL,
        "codFor": COD_FOR,
        "tipoProcessamento": 1,
        "tnsPro": "90403",
        "obsOcp": OBS_OCP,
        "produtos": [
            {
                "codPro": i["codpro"],
                "qtdPed": i["qtd"],
                "preUni": i["preco"],
                "uniMed": "UN",
                "codDep": CODDEP,
            }
            for i in ITENS
        ],
    }],
}

client = zeep.Client(WSDL)
msg = client.create_message(
    client.service, "GravarOrdensCompra_5",
    user=USER, password="****", encryption=0, parameters=parameters,
)
xml = etree.tostring(msg, pretty_print=True).decode()
xml = re.sub(r"(<password>).*?(</password>)", r"\1****\2", xml)
print(xml)

saida = Path(__file__).parent / "teste_envelope_oc.xml"
saida.write_text(xml, encoding="utf-8")
print(f"\n(salvo em {saida})")
