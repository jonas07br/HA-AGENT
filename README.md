# HA-AGENT

Sistema IoT inteligente com **Home Assistant, MQTT, WhatsApp e um agente LLM**. O usuário
conversa pelo WhatsApp em linguagem natural, e o agente consulta os sensores, controla
dispositivos e decide quais ações executar, sempre dentro de limites de segurança.

Projeto da Unidade III da disciplina Tecnologias de Comunicação para IoT (IMD0907).
**Entrega: 09/12/2026.**

## O que o sistema faz

- Gera e publica temperatura e umidade em MQTT (sensor virtual simulando um ESP).
- Mostra os dados em um dashboard no Home Assistant, com histórico e controles.
- Envia alertas automáticos pelo WhatsApp quando uma condição crítica é detectada (por
  exemplo, temperatura acima de 30 °C), por uma automação fixa que não depende do LLM.
- Permite controlar dispositivos (ventilador, lâmpada, bomba d'água) por mensagens no
  WhatsApp.
- Entende pedidos em linguagem natural por meio de um agente LLM com ferramentas.
- Tem **modos por contexto** (dormir, ausente, estufa), com regras diferentes em cada um.

Exemplos de mensagens:

- "Tá quente aí? Liga o ventilador se passar de 28°."
- "Como foi a temperatura nas últimas 3 horas?"
- "Me avisa quando a umidade cair abaixo de 40%."

## Arquitetura

```
Sensor virtual --MQTT--> Mosquitto <--> Home Assistant
                            ^  |
                            |  v
WhatsApp <--> Bot (whatsapp-web.js) <--MQTT--> Agente LLM (Ollama + tools)
```

| Componente | Função |
|---|---|
| **Sensor virtual** | Script que simula um ESP: publica temperatura e umidade, com cenários como onda de calor e falha de sensor, e simula os atuadores. |
| **Mosquitto** | Broker MQTT, integrado ao Home Assistant. |
| **Home Assistant** | Entidades MQTT, dashboard, histórico e automações fixas. As regras críticas ficam aqui. |
| **Bot WhatsApp** (Node.js, `whatsapp-web.js`) | Ponte entre o WhatsApp e o MQTT, nos tópicos `bot/entrada` e `bot/saida`. Não decide nada. |
| **Agente LLM** (Python) | Escuta `bot/entrada`, chama o modelo, executa as ferramentas e responde em `bot/saida`. |
| **Modelo** (Ollama, local) | Começamos com `qwen2.5:3b`, com `qwen2.5:7b` como alternativa. |

### Ferramentas do agente (proposta)

`ler_sensor`, `consultar_historico`, `controlar_dispositivo`, `listar_dispositivos` e
`definir_modo`.

## Segurança

O agente roda com várias camadas de proteção:

- lista de números autorizados (mensagens de outros números são ignoradas);
- allowlist de ações: só as ferramentas declaradas, nunca tópicos MQTT arbitrários;
- confirmação para ações sensíveis;
- limites de tempo de acionamento e de mensagens por minuto;
- log de auditoria (quem pediu, o que o agente entendeu, o que foi executado);
- fallback: se o LLM falhar, as automações do Home Assistant continuam e o bot aceita
  comandos simples.

Segredos (`.env`, sessão do WhatsApp, tokens do Home Assistant) não são versionados.

## Como rodar

Pré-requisitos: Docker (Docker Desktop, OrbStack ou Colima) e Python 3.

**1. Criar os usuários do broker** (o arquivo `passwd` não é versionado). Cada comando
pede a senha duas vezes. Use uma senha diferente para cada usuário e guarde-as.

O primeiro usuário é criado com `-c`, que cria o arquivo:

```bash
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c /mosquitto/config/passwd homeassistant
```

Os outros três vão **sem `-c`**. Com `-c`, o arquivo seria recriado e o usuário anterior
apagado:

```bash
for u in simulador bot agente; do
  docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
    mosquitto_passwd /mosquitto/config/passwd $u
done
```

Para conferir (devem aparecer os 4 nomes; a senha fica só como hash):

```bash
cut -d: -f1 mosquitto/config/passwd
```

Para trocar a senha de um usuário depois, rode o comando sem `-c` só para ele.

Onde cada senha é usada:

| Usuário | Onde a senha vai |
|---|---|
| `homeassistant` | Só na tela da integração MQTT do HA (passo 3) |
| `simulador` | `simulador/.env` |
| `bot` | `bot/.env` |
| `agente` | `agente/.env` |

As permissões de cada usuário estão em `mosquitto/config/acl`.

**2. Subir o broker e o Home Assistant:**

```bash
docker compose up -d
docker compose logs -f mosquitto
```

**3. Configurar o Home Assistant:** abrir `http://localhost:8123`, criar a conta e
adicionar a integração **MQTT** (Configurações > Dispositivos e serviços) com servidor
`mosquitto`, porta `1883`, usuário `homeassistant` e a senha criada no passo 1.

**4. Rodar o sensor virtual:**

```bash
cd simulador
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# editar .env com a senha do usuário "simulador"
python sensor_virtual.py
```

O cenário pode ser trocado pelo dashboard (aba Simulação), por
`python sensor_virtual.py --cenario onda_de_calor` ou publicando o nome do cenário em
`simulador/cenario/set`.

## Autores
  ### Jonas Rafael Silva Cavalcanti


  ### RAFAEL SILVA BRITTO

## Uso de IA
  #todo