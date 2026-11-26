# Sign-in with Authentik

The usual Compose signs users in with their Navidrome user and password. To add a **Entrar con Authentik**
button (OpenID Connect), enable the configuration below. The web app and the Android app both use it; Android
opens the sign-in page in an external browser.

## Provider and group

1. In the Authentik admin, create the group `armonia` in **Directory → Groups** and add the users who may enter.
2. In **Applications → Applications → Create with Provider**, create the Armonia application, slug `armonia`, with an
   OAuth2/OpenID provider. Choose a **confidential** client, the **Authorization Code** grant, a per-application
   issuer and an RSA signing key for **RS256**. Keep the client ID and store its secret on the server.
3. Select the **openid** and **profile** mappings and include the claims in the ID token. The profile mapping must
   emit `groups` as a list of names. For a new install, choose **User UUID** as the subject mode, and keep the
   chosen mode once users are linked.
4. Register the **strict** redirect URI `https://music.example/api/oidc/callback`. In the application, open
   **Policy / Group / User Bindings**, bind the group `armonia` and check the result with one user in the group and
   one without access. [Authentik OAuth2 provider](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/)

## Server configuration

Store the client secret in `secrets/oidc-client-secret`, readable by the container's UID and with mode `0600`. In
the install's `.env`:

```dotenv
COMPOSE_FILE=docker-compose.yml:compose.authentik.yaml
MUSIC_PUBLIC_ORIGIN=https://music.example
MUSIC_COOKIE_SECURE=true
MUSIC_OIDC_ISSUER=https://identity.example/application/o/armonia/
MUSIC_OIDC_CLIENT_ID=armonia
MUSIC_OIDC_GROUP=armonia
```

Use the exact `issuer` value of the discovery document, including the trailing slash if it has one. The server
reads discovery and the public keys and exchanges the code over HTTPS, so the browser and Armonia must both reach
the same issuer. If you already use `compose.metadata.yaml`, keep it in `COMPOSE_FILE`. You can leave
`MUSIC_OIDC_GROUP` out to let Authentik alone decide who may enter.

The [overlay](../compose.authentik.yaml) mounts the secret through `MUSIC_OIDC_SECRET_FILE` and reserves
`10.253.248.2/32` as Navidrome's trusted source on the private `library` network. If that subnet is taken, choose a
free one with `MUSIC_LIBRARY_SUBNET` and an address in it with `MUSIC_PROXY_IP`. With an external Navidrome, set
`ExtAuth.UserHeader=X-Armonia-User` and limit `ExtAuth.TrustedSources` to the address Armonia connects from. The
entry proxy must keep the public Host header.
[Navidrome external authentication](https://www.navidrome.org/docs/usage/integration/authentication/)

## Linking an existing music account

The operator checks the Authentik identity and the music account in their own admin pages. With **User UUID**,
use the `uuid` field of the Authentik user as the subject. Copy the Navidrome user's native ID from its record (it
also appears as `userId` in `/api/me` when signed in with the local account). The command asks once for that
account's password, in a private prompt:

```sh
docker compose exec music python -m tools.bind_oidc \
  --subject AUTHENTIK_USER_UUID \
  --user-id NAVIDROME_NATIVE_ID --username music_user
```

Armonia checks the password and the ID against Navidrome and stores the unique association
`(issuer, subject) → user_id` in its own SQLite, with the derived Subsonic credential encrypted. The bootstrap also
connects the Aurral account already assigned in the stack; for Aurral accounts with their own credentials, link
them once in **Ajustes → Recomendaciones**. Koito is chosen by the music ID and uses the private token configured for
that account. Creating music users is still the administrator's job: an OIDC identity without an association is
refused.

On each Authentik sign-in, Armonia asks Navidrome `/api/user/{id}` with the private header and checks the current
ID, user name, libraries and role, and pings with the individual credential to make sure it still works. Music
requests keep using that individual Subsonic pair, also in background jobs. Navidrome invalidates the pair when
the music password changes; run the link command again to renew it.

## Return addresses

| Client | Return |
| --- | --- |
| Authentik to Armonia (all clients) | `https://music.example/api/oidc/callback` |
| Web, after the code is accepted | `https://music.example/?oidc=done` |
| Android release / debug | `io.github.davalonie.armonia://oidc/callback` / `io.github.davalonie.armonia.debug://oidc/callback` |

Only the HTTPS return to the server is registered in Authentik. The transaction lasts ten minutes and uses state,
nonce, PKCE S256 and a temporary HttpOnly SameSite=Lax cookie bound to the browser. The web session stays in an
HttpOnly SameSite=Strict cookie, and every operation keeps its origin and owner checks. Android receives a
one-time intermediate code valid for 90 seconds; only the app that created the verifier can redeem it on the chosen
server. The pending verifier and the session are encrypted with Android Keystore. If you build the app with a
custom `-PmusicApplicationId`, set the same base ID in `MUSIC_ANDROID_APPLICATION_ID` on the server.

Signing out of Armonia revokes the Armonia session. Authentik keeps its own browser session and may reuse it on the
next sign-in; to pick another identity, switch user or sign out in Authentik.
