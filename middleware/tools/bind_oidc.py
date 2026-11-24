"""Provision one explicit (issuer, subject) association in this installation."""
import argparse
import asyncio
from getpass import getpass

import db
from homelab import integrations
from services import navidrome_client as nd
from services import oidc


async def enroll(subject, username, user_id):
    config = oidc.provider()
    password = getpass("Contraseña de la cuenta de Navidrome: ")
    context = await nd.get_user_context(username, password)
    if context.get("id") != user_id:
        raise SystemExit("La contraseña y el ID de Navidrome deben corresponder a la misma cuenta.")
    salt, token = nd.make_credentials(password)
    await integrations.link_on_login(user_id, username, password)
    oidc.bind(config.issuer, subject, user_id, username, salt, token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--user-id", required=True)
    args = parser.parse_args()
    if not db.DB_PATH.is_file():
        parser.error("Ejecuta el comando en una instalación inicializada")
    # The server owns database initialization and job recovery.
    asyncio.run(enroll(args.subject, args.username, args.user_id))
    print("Vinculación guardada.")
