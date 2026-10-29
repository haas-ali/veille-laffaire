"""Tests du bot « Dernière info 🚨 » (sans réseau, sans IA, sans envoi Telegram).
Lancer : python -m unittest discover -s tests -v   (depuis veille_laffaire)"""
import json, os, sys, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.argv = ["x", "--essai"]
import veille as V, selection as S, telegram as tg

NOW = time.time()


def article(titre, source, h_avant=1.0, typ="article"):
    return {"id": titre[:8] + source, "titre": titre, "source": source, "lien": f"https://{source.replace(' ', '').lower()}.fr/a?x=1",
            "ts": NOW - h_avant * 3600, "pays": "FR", "type": typ, "resume": "", "date": "29/10 12:00"}


def evenement(eid, analyse, articles):
    return {"id": eid, "cree": min(a["ts"] for a in articles), "maj": NOW, "articles": articles, "notifie": False, "statut": "nouveau",
            "analyses": 1, "sources_analyse": 0, "nb_sources": len({a["source"] for a in articles}), "score": 10, "analyse": analyse}


def analyse(**k):
    a = {"titre": "Titre", "resume": "Résumé.", "categorie": "fait divers", "personnes": [], "lieux": [], "lieu": None,
         "sous_scores": {"narratif": 8, "interet_public": 8, "visuels": 7, "explicable": 8}, "fiabilite": "confirme",
         "banal": False, "exceptionnel": False, "rebondissement_majeur": False, "pourquoi": "Ça fait réagir.", "nouveaute": "C'est nouveau."}
    a.update(k)
    return a


MEDIAS = ["BFMTV", "Le Monde", "Le Figaro", "franceinfo", "Le Parisien", "20 Minutes", "Ouest-France"]


class Base(unittest.TestCase):
    def setUp(self):
        self.envois = []
        V.alerter = lambda ev: self.envois.append(ev["id"])  # aucun envoi réel
        V.HEURE_PARIS = lambda: V.datetime(2026, 10, 29, 15, 0)  # en journée (pas de mode nuit)
        self.etat = {"vus": {}, "evenements": {}, "envoyes": []}


class TestSelection(Base):
    def test_01_actualite_ancienne_ignoree(self):
        ev = evenement("e1", analyse(titre="Vieille affaire", lieux=["Lyon"]), [article("Vieille affaire Lyon", m, 40) for m in MEDIAS])
        self.assertFalse(V.decider(ev, self.etat))

    def test_02_nouvelle_annonce_detectee(self):
        ev = evenement("e2", analyse(titre="Incendie géant à Rouen", lieux=["Rouen"]), [article("Incendie géant à Rouen", m, 1) for m in MEDIAS])
        self.assertTrue(V.decider(ev, self.etat))
        self.assertEqual(ev["couleur"], "vert")

    def test_03_meme_affaire_plusieurs_medias_pas_de_doublon(self):
        a = dict(titre="Mort de Pengo à Trappes", personnes=["Pengo Bossio Wangi"], lieux=["Trappes"])
        ev1 = evenement("e3", analyse(**a), [article("Pengo tué à Trappes", m, 1) for m in MEDIAS[:4]])
        ev2 = evenement("e4", analyse(**dict(a, titre="Trappes : hommage à Pengo Bossio Wangi")), [article("Hommage à Pengo", m, 1) for m in MEDIAS[4:]])
        self.assertTrue(V.decider(ev1, self.etat))
        self.assertFalse(V.decider(ev2, self.etat))  # reformulé par d'autres médias : même affaire

    def test_04_rebondissement_majeur_declenche_mise_a_jour(self):
        a = dict(titre="Meurtre à Lille", personnes=["Jean Dupont"], lieux=["Lille"])
        ev1 = evenement("e5", analyse(**a), [article("Meurtre à Lille", m, 2) for m in MEDIAS])
        self.assertTrue(V.decider(ev1, self.etat))
        ev2 = evenement("e6", analyse(**dict(a, titre="Meurtre à Lille : le suspect arrêté", rebondissement_majeur=True,
                                             nouveaute="Le suspect a été interpellé ce soir.")), [article("Suspect arrêté à Lille", m, 0.5) for m in MEDIAS])
        self.assertTrue(V.decider(ev2, self.etat))
        self.assertEqual(ev2["rebond_de"], "Meurtre à Lille")  # l'alerte dit ce qui a changé

    def test_05_actualite_banale_pas_envoyee(self):
        ev = evenement("e7", analyse(titre="Accident de la route à Tours", banal=True, lieux=["Tours"]), [article("Accident à Tours", m, 1) for m in MEDIAS])
        self.assertFalse(V.decider(ev, self.etat))

    def test_06_polemique_classee(self):
        ev = evenement("e8", analyse(titre="Clash entre deux influenceuses", categorie="polemique", personnes=["Maeva Ghennam", "Nabilla"]),
                       [article("Maeva Ghennam répond à Nabilla", m, 1) for m in MEDIAS[:4]])
        self.assertTrue(V.decider(ev, self.etat))
        self.assertIn("Polémique", tg.texte_dernier(ev))

    def test_07_annonce_youtubeur_sans_presse(self):
        ev = evenement("e9", analyse(titre="Inoxtag annonce un skin Fortnite", categorie="createurs", personnes=["Inoxtag"],
                                     source_officielle=True, sous_scores={"narratif": 8, "interet_public": 9, "visuels": 9, "explicable": 9}),
                       [article("MON SKIN FORTNITE EST LÀ", "YouTube Inoxtag", 1, "video")])
        self.assertTrue(V.decider(ev, self.etat))
        self.assertEqual(ev["fiab"], "confirme")  # la personne elle-même l'annonce
        self.assertIn("Lieu : non applicable", tg.texte_dernier(ev))

    def test_08_rouge_different_du_vert(self):
        ev = evenement("e10", analyse(titre="Attentat à Nice", exceptionnel=True, lieux=["Nice"]), [article("Attentat à Nice", m, 0.5) for m in MEDIAS])
        self.assertTrue(V.decider(ev, self.etat))
        self.assertEqual(ev["couleur"], "rouge")
        self.assertTrue(tg.texte_dernier(ev).startswith("🔴"))
        # « exceptionnel » sur une rumeur non vérifiée : jamais rouge
        self.assertNotEqual(S.couleur(90, {"exceptionnel": True}, "verification"), "rouge")

    def test_09_non_confirme_identifie(self):
        ev = evenement("e11", analyse(titre="Rumeur de séparation", categorie="people", personnes=["Star Connue"], fiabilite="verification"),
                       [article("Séparation de Star Connue ?", "Public", 1)])
        V.decider(ev, self.etat)
        self.assertEqual(ev["fiab"], "verification")
        self.assertIn("En cours de vérification", tg.texte_dernier(ev))

    def test_10_cinq_boutons(self):
        kb = tg.boutons_dernier("e1", "texte")["inline_keyboard"]
        self.assertEqual([len(l) for l in kb], [2, 2, 1])
        self.assertEqual([b["callback_data"] for l in kb[:2] for b in l], ["prep1:e1", "prep2:e1", "prep3:e1", "prep4:e1"])
        self.assertIn("copy_text", kb[2][0])

    def test_11_chaque_modele_son_traitement(self):
        import ia
        self.assertEqual(len({ia.STYLES_MODELES[n] for n in (1, 2, 3, 4)}), 4)

    def test_12_copie_respecte_la_limite(self):
        t = S.texte_copie("Un très long titre " * 10, "Résumé " * 40, "29/10, Lyon", 88, "partiel", "https://www.exemple.fr/" + "x" * 300)
        self.assertLessEqual(len(t), 256)
        self.assertIn("88/100", t)

    def test_17_redemarrage_garde_la_memoire(self):
        a = analyse(titre="Affaire Martin à Brest", personnes=["Paul Martin"], lieux=["Brest"])
        self.assertTrue(V.decider(evenement("e12", a, [article("Affaire Martin à Brest", m, 1) for m in MEDIAS]), self.etat))
        etat2 = json.loads(json.dumps(self.etat))  # comme après un redémarrage (sauvegarde puis relecture)
        self.assertFalse(V.decider(evenement("e13", dict(a, titre="Brest : Paul Martin"), [article("Paul Martin Brest", m, 1) for m in MEDIAS]), etat2))

    def test_18_deux_fiches_meme_tour_un_seul_envoi(self):
        a = analyse(titre="Explosion à Marseille", personnes=[], lieux=["Marseille", "La Joliette"])
        evs = [evenement(f"e2{i}", dict(a), [article("Explosion à Marseille La Joliette", m, 1) for m in MEDIAS]) for i in range(2)]
        self.assertEqual([V.decider(ev, self.etat) for ev in evs], [True, False])
        self.assertEqual(len(self.envois), 1)

    def test_20_aucun_secret_dans_les_messages(self):
        ev = evenement("e30", analyse(titre="Test"), [article("Test", m, 1) for m in MEDIAS])
        V.decider(ev, self.etat)
        txt = tg.texte_dernier(ev)
        for cle in ("TELEGRAM_TOKEN", "GEMINI_API_KEY", "YOUTUBE_API_KEY"):
            v = os.environ.get(cle)
            if v:
                self.assertNotIn(v, txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
