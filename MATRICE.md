# Exigences, modules, tests

| Exigence | Module | Test |
|---|---|---|
| US01 R01 foyer et principal uniques | `services/auth.py`, schéma 001 | `test_un_seul_foyer_et_session`, `test_bootstrap_concurrent_et_atomique`, `test_contraintes_du_schema_initial` |
| US01 R02 local, sans réseau | `launcher.py`, gabarits, CSS | `test_pas_de_reseau_externe_ni_d_exposition` ; écoute 127.0.0.1 |
| US02 US03 R04 R05 R06 statuts, préavis, repère minimal | `services/milestones.py`, `present.py` | `test_bornes_de_statut`, `test_statuts_archives_et_couches`, `test_minuit_et_heure_d_ete_europe_berlin` |
| US04–US07 R07 R08 R09 R10 R16 décision | `services/decisions.py` | `test_scellement_resultat_et_nouvelle_page` |
| US08 US09 US14 R03 R14 R15 R17 R21 coffre | `services/vault.py` | `test_depot_invalide_et_panne`, `test_droits_separes_revocation_et_retrait` |
| US10 US11 US12 R11 R12 R13 R19 R23 personnes et accès | `services/people.py` | `test_droits_separes_revocation_et_retrait` |
| US13 R22 archives | `services/milestones.py` | `test_statuts_archives_et_couches` |
| US15 R24 sauvegarde | `services/backup.py`, `cli.py` | `test_sauvegarde_et_restauration` |
| R18 R20 hors périmètre | revue du dépôt | `test_perimetre_exclu_absent_du_code` ; aucun autre répertoire modifié |
| CSRF, hôte, origine, limite de tentatives | `http.py`, `security.py` | `test_securite_des_requetes` |
