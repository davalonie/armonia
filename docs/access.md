# Access and library files

Armonia signs accounts in through Navidrome (or Authentik, see [authentik.md](authentik.md)). Assign each account
its library in Navidrome before importing music. Armonia and Navidrome must see the same files at their own
mount points (`/music` in both containers of the main Compose file).

## Writing and deleting files

Armonia writes downloaded files to a temporary directory and checks the permissions again before moving them into
the library. Each user writes only into the library folder that Navidrome assigns to them.

Deleting songs needs a Navidrome administrator account **and** an explicit entry in `MUSIC_DELETE_USERS`
(comma-separated user names) on the `music` service. The main Compose file sets it empty, so nobody can delete
files until you override it in a local Compose file (see [installation.md](installation.md#options-in-env)).

## Ports

The web app and Android use Armonia's public API on port 8000. Internal port 8001 is reserved for the stack's
integrations (Aurral) and must never be published. The local Compose publishes the web app on the loopback
interface only; set up HTTPS in front of it to open the library from other devices.

## Backups

Keep the installation keys and the music apart. `runtime/` and `secrets/` hold private state. Include both in
your backups and test a restore before moving to another server. `tools/release/deploy.py` also writes an
encrypted backup of Armonia's data and configuration to `backups/` before each update.
