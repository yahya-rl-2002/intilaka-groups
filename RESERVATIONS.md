# Gestion des réservations — Intilaka Group

## Démarrer le site

Dans le dossier du projet, lancez :

```bash
python3 server.py
```

Le site public est disponible sur `http://127.0.0.1:4173`.

L'administration est disponible sur `http://127.0.0.1:4173/admin`.

Il faut utiliser `server.py` : un simple serveur statique ne peut pas enregistrer les réservations.

## Première connexion

1. Ouvrez `/admin` immédiatement après le premier lancement.
2. Créez un mot de passe administrateur d'au moins 10 caractères.
3. Conservez ce mot de passe dans un gestionnaire de mots de passe.

Le mot de passe n'est jamais stocké en clair. Il n'existe pas de mot de passe par défaut.

## Gérer les demandes

Le tableau de bord permet de :

- afficher une journée complète dans le calendrier ;
- basculer entre les vues Jour, Semaine et Mois ;
- passer au jour précédent, au jour suivant ou revenir à aujourd'hui ;
- voir chaque client dans son créneau horaire ;
- filtrer le calendrier par service et par statut ;
- imprimer la période actuellement affichée ;
- ouvrir la fiche complète d'un rendez-vous depuis le calendrier ;
- modifier directement le statut depuis le calendrier ;
- basculer entre les vues Calendrier et Liste ;
- consulter toutes les réservations ;
- rechercher par nom, téléphone ou référence ;
- filtrer par statut ;
- passer une demande en attente, confirmée, terminée ou annulée ;
- ajouter des notes internes ;
- ouvrir directement le WhatsApp du client ;
- exporter toutes les données au format CSV.

Un créneau confirmé ou en attente ne peut pas être réservé deux fois. Un créneau redevient disponible lorsque sa réservation est annulée.

## Données et sauvegarde

Les données sont conservées dans `data/intilaka.db`.

Pour sauvegarder les réservations, arrêtez le serveur puis copiez ce fichier dans un emplacement sécurisé. Vous pouvez aussi utiliser le bouton **Exporter CSV** depuis l'administration.

Ne publiez jamais le fichier `data/intilaka.db` dans un dépôt public : il contient des données personnelles de clients.

## Accès depuis un téléphone sur le même Wi-Fi

```bash
INTILAKA_HOST=0.0.0.0 python3 server.py
```

Ouvrez ensuite `http://ADRESSE-IP-DU-MAC:4173` sur le téléphone. L'ordinateur et le téléphone doivent être connectés au même réseau.

## Mise en ligne

Pour un usage réel, déployez l'application derrière HTTPS sur un hébergement qui exécute Python et conserve un disque persistant. Sauvegardez régulièrement la base SQLite. L'accès `/admin` doit rester protégé par un mot de passe fort.
