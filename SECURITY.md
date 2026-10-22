# Security

Wine Cellar runs inside your Home Assistant and is reached through Home Assistant's own sign-in (ingress). It has no accounts of its own and no open port outside the add-on.

If you find a security problem, please do **not** open a public issue. Use GitHub's private reporting instead: *Security → Report a vulnerability* on this repository. You will get a reply as soon as possible.

Useful to know when you report:
- which version of the add-on you run (Settings → Add-ons → Wine Cellar),
- what an attacker would need (network access, a Home Assistant login, a crafted file),
- the smallest steps that show the problem.

The only data that leaves your home is described in [`wine_cellar/DOCS.md`](wine_cellar/DOCS.md) under *Privacy*.
