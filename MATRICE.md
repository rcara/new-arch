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
| V2B migration 003 | `migrations/003_v2_foundation.sql`, `db.py` | `test_migration_002_to_003_on_copied_v1` |
| V2B tâches + récurrence | `services/tasks.py` | `test_task_recurrence_and_home`, `test_next_due_date_recurrence` |
| V2B événements + recherche | `services/events.py`, `services/search.py` | `test_event_and_search` |
| V2B liens ACL | `services/links.py` | `test_links_acl_and_search_privacy` |
| V2C montants / splits | `money.py` | `test_parse_amount_rejects_float`, `test_split_equal_and_percent_exact_sum` |
| V2C dépenses + remboursements | `services/finance.py` | `test_expense_split_reimbursement_no_double_count` |
| V2C confidentialité finances | `services/finance.py` | `test_finance_privacy_private_transaction` |
| V2C CSV / UI | `routes` + templates | `test_finance_csv_roundtrip` |
| V2D inventaire + garanties | `services/inventory.py` | `test_item_warranty_deadline_and_links` |
| V2D confidentialité biens | `services/inventory.py` | `test_inventory_privacy` |
| V2D cession / historique | `services/inventory.py` | `test_transfer_and_dispose` |
