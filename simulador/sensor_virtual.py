"""
Sensor virtual que simula um ESP com temperatura, umidade e tres atuadores.

Publica as leituras no MQTT, recebe comandos para ventilador, lampada e bomba e
publica o estado deles de volta. Os atuadores influenciam a simulacao: o ventilador
baixa a temperatura e a bomba aumenta a umidade.

Cenarios (trocados pelo topico simulador/cenario/set ou por --cenario):
    normal, onda_de_calor, queda_de_umidade, falha_de_sensor
"""

import argparse
import math
import os
import random
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

def env(nome):
    try:
        return os.environ[nome]
    except KeyError:
        raise SystemExit(f"Variavel {nome} ausente. Defina no arquivo simulador/.env")


MQTT_HOST = env("MQTT_HOST")
MQTT_PORT = int(env("MQTT_PORT"))
MQTT_USER = env("MQTT_USER")
MQTT_PASSWORD = env("MQTT_PASSWORD")
INTERVALO = float(env("INTERVALO_SEGUNDOS"))

# duracao de um "dia" simulado
PERIODO_DIA = float(env("PERIODO_DIA_SEGUNDOS"))

TOPICO_TEMPERATURA = "casa/sensor/temperatura"
TOPICO_UMIDADE = "casa/sensor/umidade"
TOPICO_STATUS = "casa/sensor/status"
TOPICO_CENARIO_SET = "simulador/cenario/set"
TOPICO_CENARIO_ESTADO = "simulador/cenario/estado"

DISPOSITIVOS = ("ventilador", "lampada", "bomba")
CENARIOS = ("normal", "onda_de_calor", "queda_de_umidade", "falha_de_sensor")

# fracao da distancia ate o alvo percorrida a cada leitura (inercia do ambiente)
INERCIA = 0.08


class Simulador:
    def __init__(self, cenario):
        self.cenario = cenario
        self.temperatura = 25.0
        self.umidade = 60.0
        self.dispositivos = {nome: "OFF" for nome in DISPOSITIVOS}
        self.inicio = time.time()

    def alvos(self):
        # simula uma curva senoidal de temperatura e umidade ao longo do dia
        fase = 2 * math.pi * (time.time() - self.inicio) / PERIODO_DIA
        alvo_temp = 25.0 + 2.5 * math.sin(fase)
        alvo_umid = 60.0 - 6.0 * math.sin(fase)

        if self.cenario == "onda_de_calor":
            alvo_temp += 9.0
            alvo_umid -= 10.0
        elif self.cenario == "queda_de_umidade":
            alvo_umid -= 30.0

        # efeito dos atuadores sobre o ambiente
        if self.dispositivos["ventilador"] == "ON":
            alvo_temp -= 3.0
        if self.dispositivos["bomba"] == "ON":
            alvo_umid += 15.0

        return alvo_temp, alvo_umid

    def passo(self):
        alvo_temp, alvo_umid = self.alvos()
        # suaviza mudanca de valores
        self.temperatura += (alvo_temp - self.temperatura) * INERCIA
        self.umidade += (alvo_umid - self.umidade) * INERCIA

        # simula ruido
        self.temperatura += random.gauss(0, 0.1)
        self.umidade += random.gauss(0, 0.3)
        self.umidade = min(100.0, max(0.0, self.umidade))


def publicar_estado_dispositivo(cliente, nome, estado):
    # retido para o HA saber o estado mesmo se reiniciar
    cliente.publish(f"casa/dispositivo/{nome}/estado", estado, qos=1, retain=True)


def publicar_status(cliente, sim):
    # em falha de sensor o HA mostra temperatura e umidade como indisponiveis
    status = "offline" if sim.cenario == "falha_de_sensor" else "online"
    cliente.publish(TOPICO_STATUS, status, qos=1, retain=True)


def ao_conectar(cliente, sim, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[mqtt] falha ao conectar: {reason_code}")
        return
    print(f"[mqtt] conectado em {MQTT_HOST}:{MQTT_PORT}")

    # assina comandos dos atuadores (so os da lista) e a troca de cenario
    for nome in DISPOSITIVOS:
        cliente.subscribe(f"casa/dispositivo/{nome}/set", qos=1)
    cliente.subscribe(TOPICO_CENARIO_SET, qos=1)

    # (re)publica o estado completo a cada conexao
    publicar_status(cliente, sim)
    cliente.publish(TOPICO_CENARIO_ESTADO, sim.cenario, qos=1, retain=True)
    for nome, estado in sim.dispositivos.items():
        publicar_estado_dispositivo(cliente, nome, estado)


def ao_receber(cliente, sim, msg):
    payload = msg.payload.decode(errors="replace").strip()

    if msg.topic == TOPICO_CENARIO_SET:
        if payload not in CENARIOS:
            print(f"[cenario] ignorado, desconhecido: {payload!r}")
            return
        sim.cenario = payload
        print(f"[cenario] agora: {payload}")
        publicar_status(cliente, sim)
        cliente.publish(TOPICO_CENARIO_ESTADO, payload, qos=1, retain=True)
        return

    # topico no formato casa/dispositivo/<nome>/set
    partes = msg.topic.split("/")
    nome = partes[2] if len(partes) == 4 else None
    if nome not in DISPOSITIVOS:
        return

    comando = payload.upper()
    if comando not in ("ON", "OFF"):
        print(f"[{nome}] comando ignorado: {payload!r}")
        return

    sim.dispositivos[nome] = comando
    print(f"[{nome}] {comando}")
    publicar_estado_dispositivo(cliente, nome, comando)


def main():
    parser = argparse.ArgumentParser(description="Sensor virtual (simula um ESP)")
    parser.add_argument("--cenario", choices=CENARIOS, default="normal")
    args = parser.parse_args()

    simulador = Simulador(args.cenario)

    cliente = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="sensor-virtual",
        userdata=simulador,
    )
    cliente.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    # se o script cair sem desconectar, o broker avisa o HA
    cliente.will_set(TOPICO_STATUS, "offline", qos=1, retain=True)
    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber

    cliente.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    cliente.loop_start()

    print(f"[simulador] cenario inicial: {simulador.cenario}. Ctrl+C para sair.")
    try:
        while True:
            simulador.passo()
            # em falha de sensor o "ESP" continua vivo, mas o sensor para de responder
            if simulador.cenario != "falha_de_sensor" and cliente.is_connected():
                temp = f"{simulador.temperatura:.1f}"
                umid = f"{simulador.umidade:.1f}"
                cliente.publish(TOPICO_TEMPERATURA, temp, qos=0)
                cliente.publish(TOPICO_UMIDADE, umid, qos=0)
                print(f"[simulador] {temp} °C  {umid} %  ({simulador.cenario})")
            time.sleep(INTERVALO)
    except KeyboardInterrupt:
        print("\n[simulador] encerrando")
    finally:
        # saida limpa nao dispara o last will, entao avisa manualmente
        info = cliente.publish(TOPICO_STATUS, "offline", qos=1, retain=True)
        try:
            info.wait_for_publish(2)
        except (RuntimeError, ValueError):
            pass
        cliente.loop_stop()
        cliente.disconnect()


if __name__ == "__main__":
    main()
