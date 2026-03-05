# Teleport Local AI Demo and Dev Env

Local Teleport cluster for MCP demo, encapsulated so it can run entirely locally to your laptop.

## Prerequisites

- [docker](https://docs.docker.com/desktop/setup/install/mac-install/)

## Cluster setup

Update `teleport.yaml` to change `run_as_local_user` to your username.

To start server:

```bash
gmake start
```

`sudo` will be ran so put in your password, needed for `mkcert -install` and updating `/etc/hosts`.

Open browser and visit: `https://teleport.demo:34443`

To activate local environment and binaries:

```bash
source source_activate_binaries
```

Create an `admin` user:

```bash
tctl users add admin --roles editor,access,auditor,reviewer --db-users "*" --db-names "*"
```

Create an `ai` user:

```bash
tctl create resource_role_access-mcp-dev.yaml
tctl create resource_role_access-db-dev-readonly.yaml
tctl users add ai_user --roles access-mcp-dev,access-db-dev-readonly,auditor,requester
```

Login as `ai` user:

```bash
tsh login --user ai_user --proxy teleport.demo:34443
tsh mcp ls
tsh mcp config --all --client-config claude
```

## Database setup

Start local postgres container:

```bash
tctl auth sign --format=db --host=localhost --out=postgres --ttl=2190h
gmake postgres
```

Connect directly:

```bash
docker exec -e POSTGRES_PASSWORD=test -it postgres psql --username postgres test
```

Connect as ai_user:

```bash
tsh db connect --db-user read-only --db-name test my-postgres-sales
```

For mcp, drop this in any MCP compatible client to add DB support

```json
{
  "mcpServers": {
    "teleport-db-access-test": {
      "command": "{{PATH TO REPO DIR}}/mcp-local-demo/teleport-ent/tsh.app/Contents/MacOS/tsh",
      "args": [
        "mcp",
        "db",
        "--db-user=read-only",
        "--db-name=test"
      ],
      "env": {
        "TELEPORT_HOME": "{{PATH TO REPO DIR}/mcp-local-demo/.tsh"
      }
    }
  }
}
```
