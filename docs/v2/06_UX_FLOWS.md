# Parcours UX V2

Interface **française** par défaut. Navigation cible : Accueil, Finances*, Inventaire*, Calendrier, Organisation, Coffre, Décisions, Médiathèque*, Foyer, Paramètres*, Recherche — `*` masqué si module désactivé. Repères reste accessible (capacité Index V1).

## Socle B — parcours livrés

### Accueil
Vue transversale réelle : urgences repères, tâches ouvertes à échéance proche, événements des 30 prochains jours. États vides actionnables.

### Organisation — tâche récurrente
1. Organisation → Nouvelle tâche  
2. Titre, priorité, assigné optionnel, échéance, récurrence  
3. Enregistrer → visible Accueil si ouverte  
4. Marquer faite → quitte la liste active ; récurrence crée la suivante (weekly/monthly/…)

### Calendrier — événement
1. Calendrier → Nouvel événement  
2. Titre, date (journée entière par défaut), responsable  
3. Visible Accueil (fenêtre 30 j) et liste calendrier

### Lien objet
Depuis une tâche : lier un repère (`task` → `milestone`, `relates_to`). Lecture refusée si l’acteur n’a pas Index.

### Recherche
Champ global : requêtes sur titres de repères/tâches/événements et décisions accessibles (titre/choix seulement si droit).

### Parcours V1 conservés
Dépense partagée, inventaire, médiathèque : documentés pour C–E, non livrés en B.
