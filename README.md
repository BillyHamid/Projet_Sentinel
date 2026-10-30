# Sentinel Lab — guide pour la démonstration

**Sujet : Détection en temps réel d’une surcharge HTTP sur une API locale par autoencodeur.**

Le prototype fait réellement communiquer un client HTTP et une API FastAPI sur cet ordinateur. Les graphiques proviennent des requêtes observées. Un réseau de neurones PyTorch entraîné calcule les scores ; le simulateur ne commande pas les alertes.

## Démarrer demain

1. Ouvrir ce dossier dans l’Explorateur Windows et double-cliquer sur **DEMARRER.bat**.
2. Garder la fenêtre de lancement ouverte. Le navigateur s’ouvre sur **http://127.0.0.1:8765** dès que le serveur répond.
3. Si le modèle sauvegardé est présent, il est immédiatement chargé. Si l’ordinateur ou ses conditions de charge ont changé, cliquer sur **Calibrer le modèle** et attendre environ deux minutes. Garder le PC dans les mêmes conditions que pendant la présentation.
4. Vérifier que le trafic normal reste en dessous du seuil. Cliquer sur **Lancer la surcharge** : le scénario dure au maximum 25 secondes.
5. Observer les mesures, les réponses HTTP 503 éventuelles et l’alerte calculée. Attendre le retour au trafic normal.
6. Le bouton **Arrêter le trafic** coupe le générateur. Les requêtes déjà en cours finissent normalement. **Ctrl+C** dans le lanceur arrête l’application.

Pour ce paquet de transfert, lire d’abord **LIRE_DABORD.txt**. Sur le PC destinataire, le lanceur exige Python 3.12 et télécharge les bibliothèques au premier démarrage. Il crée son propre environnement `.venv` dans le dossier du projet. Les utilisations suivantes ne nécessitent pas Internet. Le fichier ZIP du projet ne contient pas Python ni ces bibliothèques. Ne pas attendre la soutenance pour installer sur une autre machine.

## Déroulé oral de trois minutes

- **0:00 — Problème.** « Une API peut être submergée par des requêtes. Mon système apprend le comportement normal et signale une déviation. » Montrer les réponses HTTP et le débit normal.
- **0:30 — Deep learning.** Montrer le panneau « Le deep learning, en clair », les couches, les paramètres et les pertes d’entraînement et de validation. Le modèle a été entraîné avant cette courte démonstration ; l’inférence est exécutée en direct.
- **1:00 — Scénario contrôlé.** Cliquer sur « Lancer la surcharge ». Montrer la hausse des requêtes, des latences et des erreurs. Le service a volontairement une capacité limitée pour rendre l’effet observable sans saturer le PC.
- **1:30 — Décision du modèle.** Montrer le score divisé par le seuil. Deux fenêtres suspectes consécutives confirment l’alerte. Le délai affiché est mesuré depuis le début du scénario ; il n’est pas codé à l’avance.
- **2:00 — Récupération.** Le scénario s’arrête automatiquement et les mesures reviennent vers leur niveau normal. Montrer le journal horodaté.
- **2:30 — Limites et contrôle.** Lancer éventuellement un « Pic légitime » de 24 requêtes/s. Expliquer que la distinction entre hausse légitime et attaque reste imparfaite et doit être évaluée sur davantage de situations. Exporter les mesures CSV.

## Où est le deep learning ?

Il se trouve dans **detector.py**. C’est un vrai réseau PyTorch à couches denses :

`6 → 12 → 6 → 2 → 6 → 12 → 6`

Les couches cachées utilisent `Tanh`. Le réseau est optimisé par rétropropagation avec Adam, une perte MSE et une régularisation des poids. L’entraînement comporte au plus 300 époques avec arrêt anticipé. La meilleure version selon la perte de validation est conservée.

Chaque seconde environ, six caractéristiques sont calculées à partir des requêtes terminées :

| Caractéristique | Origine réelle |
|---|---|
| Requêtes par seconde | Nombre de réponses / durée réelle de la fenêtre |
| Latence p95 | 95e percentile des durées mesurées côté API, attente comprise |
| Taux d’erreur | Part des réponses HTTP de code au moins 400 |
| Latence moyenne | Moyenne des durées mesurées |
| Concurrence maximale | Maximum de requêtes simultanées observé dans la fenêtre |
| Octets par seconde | Taille des corps de réponses / durée de fenêtre |

Le prétraitement applique `log(1+x)` puis une standardisation dont les paramètres sont appris sur l’entraînement seulement. Un plancher d’écart-type évite d’amplifier les petites variations des caractéristiques presque constantes.

La calibration collecte **90 fenêtres de trafic normal réel**. Les 67 premières servent à l’apprentissage ; les 23 dernières à la validation et au réglage du seuil. Le seuil pédagogique est `max(2,5 × quantile 99 % des scores normaux de validation, 1,5)`. Ce réglage prudent n’est pas une garantie statistique avec un si petit échantillon.

Le score est la moyenne des erreurs de reconstruction au carré. Le tableau de bord affiche **score / seuil** : une valeur supérieure à 1 est suspecte. Ce nombre **n’est pas une probabilité d’attaque**. Les contributions affichées indiquent les caractéristiques mal reconstruites, sans prouver la cause de l’événement.

Le code du détecteur n’accepte que six nombres. Le nom du scénario, les boutons de l’interface et les étiquettes ne sont jamais ses entrées. Le scénario est enregistré séparément pour analyser la détection.

## Architecture du laboratoire

`Générateur HTTP → API FastAPI → mesures par seconde → autoencodeur → tableau de bord`

- Une seule application locale écoute sur **127.0.0.1:8765**. Le tableau de bord et les commandes ne sont pas comptés dans les mesures du service cible.
- La route cible est fixée à **/api/service**. Il n’existe aucun champ permettant de viser une adresse externe.
- Le trafic normal varie entre 8 et 24 requêtes/s demandées. Le débit réellement atteint dépend du PC et figure à l’écran.
- La surcharge utilise une consigne de 100 requêtes/s pendant 25 s, avec au plus 28 requêtes clientes simultanées. Cette consigne inclut tout le trafic généré pendant le scénario. Le débit de réponses observé sur une courte fenêtre peut différer, notamment à cause des requêtes qui terminent dans la fenêtre suivante.
- L’API ne traite que trois requêtes simultanément ; un traitement prend environ 55–85 ms. Une attente de plus de 100 ms pour accéder à cette capacité retourne HTTP 503.
- La collecte et l’affichage sont actualisés approximativement chaque seconde. Une alerte exige deux fenêtres successives au-dessus du seuil. Ce n’est pas du temps réel à échéance garantie.
- L’API et le générateur sont asynchrones. Le délai artificiel représente une ressource lente ; aucune boucle de calcul intensif n’est utilisée pour saturer le processeur.

## Ce que ce prototype démontre, et ses limites

Il démontre une chaîne complète avec de vraies requêtes locales, une dégradation mesurable du service et une inférence neuronale indépendante du scénario. Il s’agit d’une **simulation contrôlée de DoS HTTP**, produite par une seule machine. Ce n’est ni un botnet distribué, ni un cœur 5G, ni un déploiement IoT réel.

La calibration locale remplace ici un dataset externe : elle assure que les mesures de l’entraînement correspondent exactement à celles disponibles en direct. **CICIoT2023 n’est pas utilisé dans cette version.** Il pourrait alimenter une étude ultérieure avec un extracteur de caractéristiques compatible.

Une surcharge légitime et une attaque peuvent produire les mêmes symptômes. Les 90 fenêtres normales ne suffisent pas à prouver la généralisation, la détection d’attaques inconnues ou un taux de fausses alertes fiable. La latence du PC, la charge du navigateur ou un changement de machine peuvent nécessiter une recalibration. Le système alerte ; il ne bloque pas automatiquement les requêtes.

Les résultats du test de bout en bout dans **artifacts/validation_live.json** portent uniquement sur les scénarios locaux exécutés lors de la vérification. Ils ne sont pas des résultats de benchmark scientifique.

## Fichiers utiles

- `app.py` : API, générateur borné, collecte, alertes et commandes.
- `detector.py` : réseau de neurones, entraînement, seuil et inférence.
- `static/` : interface locale sans dépendances web externes.
- `artifacts/autoencoder.pt` : poids entraînés et paramètres du prétraitement.
- `artifacts/model.json` : architecture, paramètres, pertes et règle du seuil.
- `artifacts/normal_windows.csv` : données normales utilisées pour calibrer le modèle.
- `artifacts/session.csv` : mesures de la session courante, réinitialisées au redémarrage.
- `artifacts/validation_live.json` : résultats de la dernière vérification complète.
- `validate_live.py` : test HTTP normal, pic légitime, surcharge et récupération.
- `tests/test_detector.py` : apprentissage, détection d’un changement important, sauvegarde et entrées invalides.

## Dépannage rapide

- **Page inaccessible :** vérifier que le lanceur tourne, puis ouvrir http://127.0.0.1:8765. Le lancement initial de PyTorch peut prendre quelques secondes.
- **Port déjà utilisé :** si c’est Sentinel, le lanceur ouvre la session existante. Sinon fermer l’autre service ou définir la variable `SENTINEL_PORT` avant de lancer `app.py` (le lanceur standard utilise 8765).
- **Pas d’alerte ou fausses alertes répétées :** arrêter les scénarios, laisser le PC se stabiliser et recalibrer. Examiner les mesures et le score ; ne pas prétendre qu’une alerte a eu lieu si le seuil n’a pas été franchi.
- **Une seule fenêtre suspecte :** c’est normal que l’alerte ne soit pas confirmée. Elle exige deux fenêtres consécutives.
- **Données absentes après arrêt :** le détecteur suspend l’inférence lorsque la fenêtre ne contient aucune requête.

## Vérifier soi-même

Dans un terminal ouvert dans ce dossier, utiliser le Python de l’environnement installé :

```powershell
& '.venv/Scripts/python.exe' -m pytest tests -q
& '.venv/Scripts/python.exe' validate_live.py
```

Sur une copie installée ailleurs, remplacer ce chemin par `.venv/Scripts/python.exe`. Le test en direct nécessite le serveur déjà lancé et effectue réellement les scénarios locaux bornés. Ne pas manipuler les boutons pendant cette vérification.
