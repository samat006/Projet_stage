from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os, json, re, random
import spacy
from PyPDF2 import PdfReader
from spire.pdf import *
import faker
import traceback

# --- Configurations ---
app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'temp_uploads'
OUTPUT_FOLDER = 'temp_output'
ALLOWED_EXTENSIONS = {'pdf'}
UNIQUE_CYRILLIC = [ 'Ё', 'Ж', 'З', 'И', 'Й', 'Л', 'П', 'Ф', 'Ц', 'Ч', 'Ш', 'Щ', 'Ъ', 'Ы', 'Ь', 'Э', 'Ю', 'Я' ]

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# --- Utils ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(path):
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)

def generate_fake_value(word, fake):
    email_pattern = r"\b[A-Za-z0-9.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    iban_pattern = r"[A-Z]{2}\d{2}\s?(?:\d{4}\s?){4,7}\d{1,4}"
    bic_pattern = r"[A-Z]{4}\s?\w{2}\s?\w{2}"

    if re.match(iban_pattern, word):
        return word[:2] + ''.join(random.choices("0123456789", k=len(word) - 2))
    elif re.match(email_pattern, word):
        return fake.email()
    elif re.match(bic_pattern, word):
        return ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=len(word)))
    elif word[0].isupper():
        return fake.name() + ''.join(c for c in word if not c.isalpha())
    else:
        return ''.join(
            str(random.randint(0, 9)) if c.isdigit()
            else random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") if c.isalpha()
            else c
            for c in word
        )

def replace_text_in_pdf(pdf_path, replacements, output_path, mask_mode=False):
    try:
        # Correction : utilisation correcte de Spire.PDF
        pdf = PdfDocument()
        pdf.LoadFromFile(pdf_path)
        
        # Itération correcte sur les pages
        for i in range(pdf.Pages.Count):
            page = pdf.Pages.get_Item(i)
            replacer = PdfTextReplacer(page)
            
            for original, new in replacements.items():
                if mask_mode:
                    # Mode masquage avec des #
                    text_to_replace = "#" * max(1, len(original) - 2)
                else:
                    text_to_replace = new
                
                # Remplacement du texte
                replacer.ReplaceAllText(original, text_to_replace)
        
        pdf.SaveToFile(output_path)
        pdf.Close()
        return True
    except Exception as e:
        print(f"Erreur dans replace_text_in_pdf: {str(e)}")
        traceback.print_exc()
        return False

def detect_entities(text):
    try:
        nlp = spacy.load("fr_core_news_sm")  # Changé de fr_core_news_lg à fr_core_news_sm
        doc = nlp(text)

        name_pattern = r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b"
        
        detected = {
            "Noms": [],
            "Emails": re.findall(r"\b[A-Za-z0-9.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text),
            "Téléphones": re.findall(r"\b(?:\+?\d{1,3}\s?)?(?:\(?\d{1,4}\)?\s?)?\d{1,4}(?:\s?\d{1,4}){1,3}\b", text),
            "IBANs": re.findall(r"[A-Z]{2}\d{2}\s?(?:\d{4}\s?){4,7}\d{1,4}", text),
            "BICs": [],
        }

        # Extraction des noms avec spaCy
        for ent in doc.ents:
            if ent.label_ == "PER" and ent.text not in detected["Noms"]:
                detected["Noms"].append(ent.text)

        # Extraction des noms avec regex
        for name in re.findall(name_pattern, text):
            if name.lower() not in ["date", "cordialement", "siret", "mail", "mode", "conditions", "nous", "au", "intracom", "code"]:
                if name not in detected["Noms"]:
                    detected["Noms"].append(name)

        # Extraire BICs uniquement après le mot "BIC"
        for segment in text.split("BIC")[1:]:
            match = re.findall(r"[A-Z]{4}\s?\w{2}\s?\w{2}", segment)
            if match:
                detected["BICs"].append(match[0])

        # Nettoyage des téléphones
        all_phones = detected["Téléphones"][:]
        detected["Nombres"] = [nb for nb in all_phones if len(nb) < 14 or len(nb) > 17]
        detected["Téléphones"] = [phone for phone in all_phones if 14 <= len(phone) <= 16]
        
        # Nettoyer les noms trop courts
        detected["Noms"] = [nom for nom in detected["Noms"] if len(nom) > 2]

        return detected
    except Exception as e:
        print(f"Erreur dans detect_entities: {str(e)}")
        # Retour par défaut en cas d'erreur
        return {
            "Noms": [],
            "Emails": re.findall(r"\b[A-Za-z0-9.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text),
            "Téléphones": [],
            "IBANs": re.findall(r"[A-Z]{2}\d{2}\s?(?:\d{4}\s?){4,7}\d{1,4}", text),
            "BICs": [],
        }

# --- Routes ---
FILTER_MAP = {
    "Noms": "names",
    "Téléphones": "phones", 
    "Nombres": "numbers",
    "Emails": "emails",
    "IBANs": "iban",
    "BICs": "bic"
}

@app.route('/api/anonymize-pdf', methods=['POST'])
def anonymize_pdf():
    input_path = None
    output_path = None
    
    try:
        print("=== DÉBUT ANONYMISATION ===")
        
        # Validation du fichier
        if 'file' not in request.files:
            return jsonify({'error': 'Aucun fichier fourni'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Aucun fichier sélectionné'}), 400
            
        if not allowed_file(file.filename):
            return jsonify({'error': 'Type de fichier invalide, seuls les PDF sont acceptés'}), 400

        # Sauvegarde du fichier
        filename = secure_filename(file.filename)
        input_path = os.path.join(UPLOAD_FOLDER, filename)
        output_path = os.path.join(OUTPUT_FOLDER, f'anonymized_{filename}')
        file.save(input_path)
        
        print(f"Fichier sauvé: {input_path}")

        # Initialisation de Faker
        fake = faker.Faker('fr_FR')  # Localisation française
        mode = request.form.get('mode', 'auto')
        print(f"Mode sélectionné: {mode}")

        if mode == "manual":
            print("=== MODE MANUEL ===")
            words = json.loads(request.form.get('words', '[]'))
            print(f"Mots à anonymiser: {words}")
            
            replacements = {}
            for word in words:
                replacements[word] = generate_fake_value(word, fake)
            
            mask_mode = request.form.get('optionManuel') == 'mask'
            print(f"Mode masquage: {mask_mode}")
            print(f"Remplacements: {replacements}")
            
            success = replace_text_in_pdf(input_path, replacements, output_path, mask_mode)
            if not success:
                return jsonify({'error': 'Erreur lors du remplacement du texte'}), 500
                
        else:
            print("=== MODE AUTOMATIQUE/FILTRÉ ===")
            filters = json.loads(request.form.get('filters', '["names","phones","emails","iban","bic"]'))
            print(f"Filtres sélectionnés: {filters}")
            
            # Extraction du texte
            text = extract_text_from_pdf(input_path)
            print(f"Texte extrait, longueur: {len(text)} caractères")
            
            # Détection des entités
            entities = detect_entities(text)
            print(f"Entités détectées: {entities}")

            # Construction des remplacements
            replacements = {}
            for key, values in entities.items():
                filter_key = FILTER_MAP.get(key, key.lower())
                if filter_key not in filters:
                    print(f"Filtre {filter_key} non sélectionné, ignoré")
                    continue
                    
                print(f"Traitement de {key}: {len(values)} éléments")
                for value in values:
                    if key == "Noms":
                        replacements[value] = fake.name()
                    elif key == "Téléphones":
                        replacements[value] = ''.join(str(random.randint(0, 9)) if c.isdigit() else c for c in value)
                    elif key == "Nombres":
                        replacements[value] = str(random.randint(1000, 99999))
                    elif key == "Emails":
                        replacements[value] = fake.email()
                    elif key == "IBANs":
                        replacements[value] = fake.iban()
                    elif key == "BICs":
                        replacements[value] = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=len(value)))

            print(f"Remplacements finaux: {replacements}")
            
            if not replacements:
                return jsonify({'error': 'Aucune donnée à anonymiser trouvée avec les filtres sélectionnés'}), 400
            
            success = replace_text_in_pdf(input_path, replacements, output_path)
            if not success:
                return jsonify({'error': 'Erreur lors du remplacement du texte'}), 500

        # Vérification que le fichier de sortie existe
        if not os.path.exists(output_path):
            return jsonify({'error': 'Le fichier anonymisé n\'a pas pu être créé'}), 500
            
        print(f"✅ Anonymisation réussie: {output_path}")
        return send_file(output_path, as_attachment=True, download_name='anonymized.pdf', mimetype='application/pdf')

    except json.JSONDecodeError as e:
        print(f"Erreur JSON: {str(e)}")
        return jsonify({'error': f'Erreur dans les données JSON: {str(e)}'}), 400
    except Exception as e:
        print(f"❌ ERREUR GÉNÉRALE: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Erreur interne: {str(e)}'}), 500

    finally:
        # Nettoyage sûr des fichiers temporaires
        for path in [input_path, output_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"Fichier temporaire supprimé: {path}")
                except Exception as e:
                    print(f"Impossible de supprimer {path}: {str(e)}")

# --- Run ---
if __name__ == '__main__':
    print("🚀 Démarrage du serveur PDF Anonymizer")
    print("📍 URL: http://localhost:5000")
    print("🔧 Mode debug: Activé")
    app.run(debug=True, host='0.0.0.0', port=5000)