# Guide d'utilisation et d'exploitation

## À quoi sert l'application

Un seul foyer, sur cette machine. New Arch V2 élargit le foyer en Home OS tout en conservant les couches V1 :

- Accueil agrège échéances de repères, tâches ouvertes et événements des 30 prochains jours (données réelles).
- Organisation (tâches) et Calendrier (événements) complètent Repères.
- Repères montrent le nom, la date, le statut et si une pièce existe. Ils ne montrent ni le fichier, ni le texte d'une décision.
- Décision conserve une page écrite avant le résultat. Le scellement fige ce texte dans l'application. Le résultat s'ajoute ensuite, une seule fois.
- Coffre reçoit les PDF, JPEG et PNG. Les ouvrir dépend d'un droit distinct.
- Recherche transversale : sans fuite des contenus privés.

Le premier compte est principal. Une autre personne peut avoir un compte, créé sur place. Le lien de parenté ne donne aucun droit. Trois droits sont indépendants : voir les repères, lire une page, ouvrir un fichier.

Il n'y a pas de paiement, d'e-mail, de rappel, de total d'argent, de coach ni d'accès d'urgence.

## Premier lancement

1. Lancer l'application. L'écran demande le nom du foyer, le fuseau (Europe/Zurich par défaut pour un nouveau foyer), votre nom, un identifiant et un mot de passe de 12 à 128 caractères, saisi deux fois.
2. Vous arrivez sur Accueil, vide.
3. Dans Personnes, ajoutez les titulaires. Un titulaire peut ne pas avoir de compte.
4. Dans Repères, créez la fiche : nom, une des sept catégories, titulaire, et le reste si vous l'avez.
5. La note ne doit contenir ni mot de passe ni numéro de compte complet. L'application ne peut pas le vérifier à votre place.
6. Pour une décision, partez de la fiche. Relisez la page, puis scellez. Plus tard, ajoutez le résultat : il ne réécrit pas le texte du début.
7. Déposez une pièce depuis le Coffre, jamais depuis Repères.

Le statut se calcule avec la date civile du foyer : expiré, sous 30 jours, sous 90 jours, à jour, ou sans date. Le préavis affiché sur la fiche ne change pas ce statut et n'envoie rien.

## Second compte

Dans Personnes, créez le compte pendant que la personne est devant la machine. Elle choisit son mot de passe. Elle voit les repères. Elle ne lit une page et n'ouvre un fichier que si vous le lui accordez, un par un, dans Accès.

Retirer une personne ferme sa session. Les fiches et les pages qui la citent restent, avec la mention « retirée ».

## Sauvegarde

Les données sont dans quatre endroits voisins : `data/metadata.sqlite`, `vault/objects/`, `media/objects/` et les journaux dans `logs/`. Copier seulement la base oublie les pièces du coffre et de la médiathèque.

Pendant que l'application tourne, dans son dossier :

```sh
python cli.py backup
```

Le programme prend un verrou, copie une base cohérente, vérifie chaque pièce (coffre **et** média), puis publie un dossier `backups/foyer-AAAAMMJJTHHMMSSZ/` avec `objects/`, `media/` et `manifest.json`. S'il échoue, ce dossier n'est pas présenté comme une sauvegarde réussie. La copie est en clair, comme le reste.

Sur Windows, voir aussi [WINDOWS.md](WINDOWS.md).

## Restauration

Arrêtez l'application. Ne restaurez pas par-dessus un foyer en cours.

```sh
python cli.py restore backups/foyer-... dossier-neuf
```

Le dossier de destination doit être vide. L'outil refuse les liens, les chemins qui sortent de l'archive, une base incohérente ou des empreintes fausses. Toutes les sessions de la copie sont révoquées. Démarrez ensuite avec `FOYER_HOME` pointant vers `dossier-neuf`, connectez-vous, et vérifiez un repère, une page scellée, une pièce du coffre et un fichier média avant d'adopter ce dossier.

Deux foyers ne se fusionnent pas.

## Dataset démo

Sur un **nouveau** `FOYER_HOME` vide uniquement :

```sh
FOYER_HOME=/chemin/foyer-demo python cli.py seed-demo
```

Comptes fictifs : `alex` / `DemoFoyer-2026!` et `camille` / `DemoCamille-2026!`. Refuse si un foyer existe déjà.

## Thème et accessibilité

Paramètres → Apparence : thème sombre (défaut) ou clair (`foyer_theme`). Lien « Aller au contenu », focus visible, `prefers-reduced-motion` respecté.

## Limites du MVP

- La base et les fichiers sont en clair. Quelqu'un qui peut lire le disque ou modifier SQLite contourne les droits et le scellement.
- Le scellement est une immutabilité de l'application. Ce n'est pas une signature ni une preuve juridique.
- Un fichier déjà téléchargé ne peut pas être repris.
- Il n'y a pas de chiffrement, pas d'écoute sur le réseau local, pas de synchronisation.
- Le mot de passe est haché avec Argon2id (mémoire 19 Mio, 2 itérations, parallélisme 1). Mesure du 20 octobre 2026 sur la machine de développement : environ 0,03 s par empreinte.
- Le cookie de session n'a pas l'attribut Secure : le serveur n'écoute qu'en HTTP sur 127.0.0.1, sans TLS.
- Remplacer une pièce efface les accords de l'ancienne. Le nouveau fichier n'est partagé que par un nouvel accord.
- Les sauvegardes déjà faites peuvent encore contenir une pièce retirée ensuite.

## Écarts tranchés pendant la réalisation

Le brief prime. Les arbitrages A01–A13 sont appliqués. Trois points du dossier de conception demandaient un choix :

- Le contrôle de version au scellement et au remplacement n'existait pas dans `schema.sql`. La migration `002_concurrency.sql` ajoute `decision.draft_version`, `stored_file.version` et `session.csrf_token`. Le fichier `001_schema.sql` reste celui du dossier.
- Le statut est calculé dans le fuseau du foyer, avec la date du jour fournie par l'application. La vue SQL `index_projection` n'est pas exposée.
- « Ne rien faire » est réécrite à chaque enregistrement de brouillon. Le schéma la rend obligatoire au scellement.
- L'écran Accès envoie l'ensemble des cases. Le serveur enregistre chaque accord ou révocation séparément.
- Les trois sites cités par le brief ne sont pas nommés dans le dossier. Aucun répertoire existant de `/srv/apps` n'a été modifié. Seul `/srv/apps/plateforme-foyer` a été créé.

Bornes techniques ajoutées pour pouvoir stocker les saisies : nom du foyer 120, identifiant 80 sans espace, nom affiché 120, parenté 120, option 500, règle 200 et lignes de 300/1000, nom de fichier 180 avec une seule extension.

## Arrêt

Fermez la fenêtre du lanceur, ou envoyez une interruption au processus. Le fichier `data/foyer.pid` est retiré à l'arrêt.
