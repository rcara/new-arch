# Rapport de tests — 20 octobre 2026

Machine : Linux, Python 3.14.4, SQLite 3.46.1, Flask 3.1.3, Waitress 3.0.2, argon2-cffi 25.1.0.
Navigateur Windows cible : non exécuté.
L'outil de navigation de l'environnement n'atteint pas le 127.0.0.1 de cette machine (page d'erreur du navigateur). Le serveur Waitress a été vérifié depuis la machine elle-même.

## Automatisés

`pytest` : 23 tests, tous réussis, en moins de 2 secondes.

- Schéma initial inchangé (empreinte du dossier de conception) et contraintes SQL exécutées.
- Statuts J−1, J, J+30, J+31, J+90, J+91, sans date ; minuit et passages à l'heure d'été et d'hiver, fuseau Europe/Berlin.
- Un seul foyer, y compris avec deux créations simultanées. Une panne au milieu de l'initialisation ne laisse rien.
- Scellement refusé si la page est incomplète, irréversible ensuite, résultat unique, nouvelle page pour un nouveau choix.
- Second compte : repères oui, page et fichier non. Accorder l'un laisse l'autre fermé. Retirer les repères laisse la page lisible sans nom, date ni montant de l'échéance. Remplacer une pièce ne transmet pas l'ancien accord. Retirer la personne coupe la session suivante. Le principal ne peut pas se retirer. La parenté ne donne aucun droit. Un titulaire sans compte ne reçoit pas d'accord.
- Dépôt refusé si l'extension est double ou si le contenu ne correspond pas. Une panne avant la validation SQL ne crée pas de pièce.
- Hôte, adresse distante, origine et jeton de sécurité refusés quand ils sont faux. Message de connexion identique pour un identifiant inconnu et un mauvais mot de passe. La limite de tentatives expire.
- Sauvegarde puis restauration : texte scellé et octets identiques, sessions révoquées, dossier non vide refusé, lien refusé, sauvegarde interrompue si une pièce manque.
- Lecture de 1 000 repères : 0,004 s dans le service, et la requête HTTP du test reste sous une seconde.
- Aucune URL externe dans le code, les gabarits ou le CSS. Le lanceur ne contient pas d'écoute ouverte. Pas de paiement, d'envoi de courriel ni de coach dans le code.

## Serveur réel

Waitress écoutait uniquement sur `127.0.0.1:8765` (`ss` le confirme). Un client HTTP sur la machine a enchaîné : création du foyer, personne sans compte, repère, brouillon, scellement, dépôt d'un PDF, puis la page Aujourd'hui. Elle indique qu'une pièce est au coffre, et ne contient ni `passeport.pdf` ni le texte de la décision. La date réelle du serveur classe un passeport au 15 mars 2027 comme « À jour », ce qui est le calcul prévu.

## Non exécutés

- Recette manuelle dans un navigateur, y compris le zoom 200 % et la largeur 375 px. La feuille de style prévoit le passage sur une colonne sous 720 px ; ce rendu n'a pas été vu.
- Recette sur un navigateur Windows.
- Débranchement physique du réseau de la machine. À la place : écoute limitée à 127.0.0.1, et aucune adresse externe dans le code.

## R01–R24

| Règle | Résultat | Preuve |
|---|---|---|
| R01 | réussi | tests foyer unique et schéma |
| R02 | partiel | écoute locale et absence d'URL externe ; pas de débranchement physique |
| R03 | réussi | la page Aujourd'hui et la fiche ne contiennent ni le nom de fichier ni le choix |
| R04 | réussi | bornes de dates |
| R05 | réussi | le préavis change la date affichée, pas le statut ; aucun envoi |
| R06 | réussi | repère sans date ni montant |
| R07 | réussi | modification et suppression refusées après scellement |
| R08 | réussi | champ de lien refusé ; déclencheur SQL |
| R09 | réussi | scellement incomplet refusé ; une seule option « Ne rien faire » |
| R10 | réussi | résultat avant scellement refusé ; second résultat refusé |
| R11 | réussi | droits indépendants |
| R12 | réussi | changer la parenté ne change pas l'accès |
| R13 | réussi | requête suivante refusée, page conservée |
| R14 | réussi | dépôt seulement par le Coffre ; présence après succès |
| R15 | réussi | identifiant deviné : 404 sans le contenu |
| R16 | réussi | nouvel identifiant de page |
| R17 | réussi | pièce relue en clair dans `vault/objects` ; aucun texte de coffre chiffré |
| R18 | réussi | seul le dossier `plateforme-foyer` a été ajouté |
| R19 | réussi | révocation puis ouverture refusée dans la même session |
| R20 | réussi | revue du code |
| R21 | réussi | nouvelle pièce non ouvrable avant un nouvel accord |
| R22 | réussi | archiver retire le repère des compteurs ; restaurer le ramène |
| R23 | réussi | page lisible sans métadonnées du repère |
| R24 | réussi | sauvegarde restaurée, sessions invalidées |
