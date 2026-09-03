"""
Ponto de entrada de produção - roda o Flask sob o waitress (servidor WSGI
com pool de threads), em vez do servidor de desenvolvimento do Flask.

"""

import os
import threading
import time
from waitress import serve
from app import app #importa a aplicação Flask do arquivo app.py
from db import oracle_db

def _varredura_periodica(intervalo_seg=300):
    while True:
        time.sleep(intervalo_seg)
        try:
            n6, n4 = oracle_db.varrer_situacao_solicitacoes()
            if n6 or n4:
                print(f"[varredura] {n6} finalizada(s), {n4} atendida(s)")
        except Exception as e:
            print(f"[varredura] erro: {e}")

# threading.Thread(target=_varredura_periodica, daemon=True).start()

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5051))
    threads = int(os.environ.get("WEB_THREADS", "8"))

    
    # Inicializa o cliente Oracle + o pool numa thread só, antes de aceitar
    # requisições - evita corrida no init_oracle_client no primeiro acesso.
    try:
        _conn = oracle_db.get_connection()
        _conn.close()
        print("Pool Oracle inicializado.")
    except Exception as e:
        print(f"AVISO: nao consegui pre-inicializar o Oracle no boot ({e}). "
              f"O servidor sobe mesmo assim.")

    print(f"Acompanha pedido - Servindo em http://{host}:{port} com {threads} threads")
    serve(app, host=host, port=port, threads=threads)
