# rtu-calendar-sync

Génère un `planning.ics` à jour à partir du planning de groupe RTU
(nodarbibas.rtu.lv), filtré sur les matières réellement suivies, et le
republie automatiquement chaque jour via GitHub Actions.

## Mise en place (une fois)

1. Crée un repo GitHub **public** et pousse ce dossier dedans :

   ```bash
   cd rtu-calendar-sync
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<ton-user>/rtu-calendar-sync.git
   git push -u origin main
   ```

2. Sur GitHub : **Settings > Actions > General > Workflow permissions**,
   vérifie que "Read and write permissions" est coché (sinon le job ne
   pourra pas commit/push le fichier).

3. Lance le workflow une première fois à la main : onglet **Actions** >
   "Update RTU calendar" > **Run workflow**. Regarde les logs : la section
   "Matières ignorées" liste tout ce qui a été exclu — vérifie qu'aucune de
   tes vraies matières n'y traîne (sinon, ajuste `MY_COURSES` dans
   `sync_calendar.py`).

4. Une fois `planning.ics` présent dans le repo, abonne-toi à cette URL :

   ```
   https://raw.githubusercontent.com/<ton-user>/rtu-calendar-sync/main/planning.ics
   ```

   - **Google Calendar** (web) : bouton `+` à côté de "Autres agendas" >
     "À partir de l'URL" > coller l'URL.
   - **iOS** : Réglages > Calendrier > Comptes > Ajouter un compte > Autre
     > Ajouter un calendrier avec abonnement > coller l'URL.

   Les deux se resynchronisent automatiquement à intervalles réguliers
   (généralement toutes les quelques heures, pas en temps réel).

## Chaque nouveau semestre

Modifie ces constantes en haut de `sync_calendar.py`, commit, push :

- `SEMESTER_LABEL_CONTAINS` (ex: `"26/27-SP"` pour le semestre de printemps)
- `MY_COURSES` si tes matières changent

## Comment ça marche

`nodarbibas.rtu.lv` expose une petite API JSON interne (pas de session à
maintenir). Le script :

1. résout le `semesterId`, `programId`, `semesterProgramId` correspondant à
   ton programme/groupe,
2. récupère tous les événements du **groupe entier** sur le semestre (le
   site ne permet pas de filtrer par étudiant, seulement par groupe),
3. ne garde que les événements dont l'intitulé correspond à une entrée de
   `MY_COURSES`,
4. génère un `.ics` avec un UID **stable** par événement (hash du contenu,
   pas un UUID aléatoire) — sans ça, chaque régénération quotidienne créerait
   des doublons au lieu de mettre à jour les événements existants.
