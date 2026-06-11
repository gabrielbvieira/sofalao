# Sofalão — Bolão da Copa 2026 (Sofa DGTL)

Bolão da Copa do Mundo 2026 em Flask + SQLite, com sincronização automática
da tabela de jogos (incluindo a descoberta dos confrontos do mata-mata).

## Como rodar

```bash
pip install -r requirements.txt
python app.py
# http://localhost:5000
```

- O **primeiro usuário cadastrado vira admin** automaticamente.
- O banco `sofalao.db` (SQLite) é criado sozinho na primeira execução.
- O arquivo `.env` é carregado automaticamente e guarda o token do football-data
  para desenvolvimento local.

## Deploy Kubernetes

O deploy de produção está preparado para o host:

```text
sofalao.sofadigital.com
```

Arquivos principais:

```text
deploy-prd.sh
k8s/sofalao-deployment.yaml
k8s/sofalao-clusterip.yaml
k8s/sofalao-ingress.yaml
k8s/sofalao-secret.yaml
```

Deploy simples, sem build de imagem e sem ECR:

```bash
./deploy-prd.sh
```

O script cria ConfigMaps com o código local, templates e arquivos estáticos,
aplica Service/Ingress/Deployment e aguarda o rollout. O pod usa a imagem
pública `python:3.12-slim` e instala as dependências quando sobe. O SQLite fica
em `/data/sofalao.db`, dentro de um `emptyDir` temporário do pod. Em produção, o
token fica em `k8s/sofalao-secret.yaml`.

## Backup Google Drive

O backup do SQLite para o Google Drive é opcional. Quando configurado, o app
envia um arquivo `sofalao-YYYYMMDD-HHMMSS.db` para a pasta escolhida a cada
6 horas (`SOFALAO_BACKUP_MIN`).

Jeito simples:

1. Crie uma credencial JSON de **Service Account** no Google Cloud.
2. Crie uma pasta no seu Google Drive.
3. Compartilhe essa pasta com o `client_email` da Service Account.
4. Copie o ID da pasta da URL do Drive.
5. Gere o JSON em base64:

```bash
base64 -w0 google-drive-credentials.json
```

6. Preencha em `k8s/sofalao-secret.yaml`:

```yaml
GOOGLE_DRIVE_FOLDER_ID: "id_da_pasta"
GOOGLE_DRIVE_CREDENTIALS_B64: "conteudo_base64_do_json"
```

Depois rode:

```bash
./deploy-prd.sh
```

Na tela Admin aparece se o backup está configurado e há um botão **Backup
agora** para testar.

## Sincronização (tabela + mata-mata)

O sync usa a API gratuita do [football-data.org](https://www.football-data.org/client/register)
(competição `WC`). Com o token definido em `FOOTBALL_DATA_TOKEN`:

- importa **todos os 104 jogos** (fase de grupos + mata-mata);
- atualiza os **placares** dos jogos encerrados;
- jogos do mata-mata aparecem como "A definir" e são **atualizados
  automaticamente** quando a FIFA define os confrontos;
- roda em background a cada 30 min (`SOFALAO_SYNC_MIN` para mudar)
  e também pelo botão **Sincronizar agora** na tela Admin;
- linha de comando: `python sync.py`.

Sem token, o admin pode cadastrar partidas e resultados manualmente
na tela Admin (tudo continua funcionando).

## Regras de pontuação

| Acerto | Pontos |
|---|---|
| Placar exato | 3 |
| Vencedor/empate (sem placar exato) | 1 |
| Quem avança nos pênaltis (mata-mata) | 2 |
| Campeão (bônus) | 10 |
| Artilheiro (bônus) | 10 |

Valores configuráveis no topo de `app.py` (`POINTS_*`).

- Palpites de jogo **travam no horário do pontapé inicial** de cada partida.
- Nos jogos de mata-mata aparece o palpite extra **"Pênaltis?"** — quem
  avança caso a decisão vá para as penalidades (o sync detecta isso sozinho
  via `score.duration = PENALTY_SHOOTOUT`; no modo manual, o admin marca).
- Palpites bônus travam no **primeiro jogo da Copa**.
- O campeão/artilheiro oficiais são definidos pelo admin (tela Admin)
  ao fim do torneio, e o bônus entra no ranking automaticamente.

## Tela bônus

A lista de atacantes por seleção fica em `forwards.json` — edite à vontade
(convocações mudam!). Também dá para digitar um jogador fora da lista.

## Estrutura

```
sofalao/
├── app.py          # rotas, regras e pontuação
├── wsgi.py         # entrada Gunicorn/produção
├── sync.py         # sync com football-data.org (importável e CLI)
├── deploy-prd.sh   # ConfigMaps + apply/rollout Kubernetes
├── k8s/            # manifests de produção
├── forwards.json   # atacantes por seleção (editável)
├── templates/      # Jinja (login, jogos, bônus, ranking, admin)
├── static/         # logo + CSS (paleta da logo Sofa DGTL)
└── sofalao.db      # criado em runtime
```

## Notas

- Horários exibidos em **horário de Brasília** (armazenados em UTC).
- Senhas com hash (werkzeug); troque `SOFALAO_SECRET` em produção.
- Para a galera acessar na rede local: `flask run --host=0.0.0.0`.
