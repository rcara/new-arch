# Contrats API V2

Base : `/api`. Auth cookie session + en-tête `X-CSRF-Token` sur mutations. Erreurs : `{ "error": { "code", "message", "fields" } }`.

## Hérité V1 (inchangé)

`POST /bootstrap`, `POST|DELETE /session`, `GET /me`, `GET /today`, CRUD repères/décisions/fichiers/personnes/accès — voir `app/routes/api.py`.

## Nouveaux (socle B)

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/home` | Accueil agrégé (repères urgents + tâches ouvertes + événements 30 j) |
| GET/POST | `/tasks` | Liste / création |
| GET/PATCH | `/tasks/<id>` | Détail / mise à jour (dont statut) |
| GET/POST | `/events` | Liste / création événements |
| GET/PATCH | `/events/<id>` | Détail / mise à jour |
| GET/POST | `/links` | Liste filtrée / création lien |
| DELETE | `/links/<id>` | Archive du lien |
| GET | `/search?q=` | Recherche transversale filtrée ACL |
| GET | `/modules` | Modules activés pour la nav |

## Invariants sécurité API

- Index / Accueil ne renvoient **jamais** nom de fichier coffre ni texte de décision.
- Recherche : hits décision/fichier limités aux objets accessibles ; pas de snippet de contenu coffre.
- Liens : 404 si objet inaccessible (pas 403 révélateur quand possible, aligné V1 fichiers).
