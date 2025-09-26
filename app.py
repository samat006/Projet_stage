from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os, json, re, random
import spacy
from PyPDF2 import PdfReader
import faker
import traceback

# Option 1: Avec Spire.PDF corrigé
try:
    from spire.pdf import PdfDocument, PdfTextReplacer
    SPIRE_AVAILABLE = True
except ImportError:
    SPIRE_AVAILABLE = False
    print("Spire.PDF non disponible, utilisation de PyMuPDF")

# Option 2: Avec PyMuPDF (plus stable)
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("PyMuPDF non disponible")

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
    try:
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        print(f"Erreur extraction texte: {e}")
        return ""

def generate_fake_value(word, fake):
    email_pattern = r"\b[A-Za-z0-9.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    iban_pattern = r"[A-Z]{2}\d{2}\s?(?:\d{4}\s?){4,7}\d{1,4}"
    bic_pattern = r"[A-Z]{4}\s?\w{2}\s?\w{2}"

    try:
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
    except Exception as e:
        print(f"Erreur génération fake: {e}")
        return "#" * len(word)

# SOLUTION 1: Spire.PDF corrigé
def replace_text_in_pdf_spire(pdf_path, replacements, output_path, mask_mode=False):
    if not SPIRE_AVAILABLE:
        raise Exception("Spire.PDF n'est pas disponible")
    
    try:
        pdf = PdfDocument()
        pdf.LoadFromFile(pdf_path)
        
        # Correction de l'erreur SpireObject
        page_count = pdf.Pages.Count
        print(f"Nombre de pages: {page_count}")
        
        for i in range(page_count):
            try:
                page = pdf.Pages.get_Item(i)
                replacer = PdfTextReplacer(page)
                
                for original, new in replacements.items():
                    text_to_replace = "#" * max(1, len(original) - 2) if mask_mode else new
                    print(f"Remplacement: '{original}' -> '{text_to_replace}'")
                    replacer.ReplaceAllText(original, text_to_replace)
                    
            except Exception as page_error:
                print(f"Erreur page {i}: {page_error}")
                continue
        
        pdf.SaveToFile(output_path)
        pdf.Close()
        print(f"PDF sauvé: {output_path}")
        
    except Exception as e:
        print(f"Erreur Spire.PDF: {e}")
        traceback.print_exc()
        raise e

# SOLUTION 2: PyMuPDF (plus stable)
def replace_text_in_pdf_pymupdf(pdf_path, replacements, output_path, mask_mode=False):
    if not PYMUPDF_AVAILABLE:
        raise Exception("PyMuPDF n'est pas disponible")
    
    try:
        doc = fitz.open(pdf_path)
        print(f"PDF ouvert, {len(doc)} pages")
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            for original, new in replacements.items():
                text_to_replace = "#" * max(1, len(original) - 2) if mask_mode else new
                
                # Chercher le texte
                text_instances = page.search_for(original)
                print(f"Page {page_num}: '{original}' trouvé {len(text_instances)} fois")
                
                for inst in text_instances:
                    # Créer une annotation de rédaction
                    page.add_redact_annot(inst, text=text_to_replace, fill=(1, 1, 1))
            
            # Appliquer les rédactions
            page.apply_redactions()
        
        doc.save(output_path)
        doc.close()
        print(f"PDF sauvé avec PyMuPDF: {output_path}")
        
    except Exception as e:
        print(f"Erreur PyMuPDF: {e}")
        traceback.print_exc()
        raise e

# Fonction principale qui choisit la meilleure méthode
def replace_text_in_pdf(pdf_path, replacements, output_path, mask_mode=False):
    print(f"Remplacement dans PDF: {len(replacements)} éléments")
    
    # Essayer PyMuPDF en premier (plus stable)
    if PYMUPDF_AVAILABLE:
        try:
            replace_text_in_pdf_pymupdf(pdf_path, replacements, output_path, mask_mode)
            return
        except Exception as e:
            print(f"PyMuPDF échoué, tentative avec Spire: {e}")
    
    # Fallback vers Spire.PDF
    if SPIRE_AVAILABLE:
        try:
            replace_text_in_pdf_spire(pdf_path, replacements, output_path, mask_mode)
            return
        except Exception as e:
            print(f"Spire.PDF échoué: {e}")
            raise e
    
    raise Exception("Aucune bibliothèque PDF disponible")

def detect_entities(text):
    fake = faker.Faker()
    
    try:
        nlp = spacy.load("fr_core_news_lg")
    except:
        try:
            nlp = spacy.load("fr_core_news_sm")
        except:
            print("Modèle spaCy français non trouvé")
            nlp = None
    
    name_pattern = r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b"

    detected = {
        "Noms": [],
        "Emails": re.findall(r"\b[A-Za-z0-9.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text),
        "Téléphones": re.findall(r"\b(?:\+?\d{1,3}\s?)?(?:\(?\d{1,4}\)?\s?)?\d{1,4}(?:\s?\d{1,4}){1,3}\b", text),
        "IBANs": re.findall(r"[A-Z]{2}\d{2}\s?(?:\d{4}\s?){4,7}\d{1,4}", text),
        "BICs": [],
    }

    # Utiliser spaCy si disponible
    if nlp:
        try:
            doc = nlp(text)
            for ent in doc.ents:
                if ent.label_ == "PER" and ent.text not in detected["Noms"]:
                    detected["Noms"].append(ent.text)
        except Exception as e:
            print(f"Erreur spaCy: {e}")

    # Regex pour les noms
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
    detected["Nombres"] = [
        nb for nb in detected["Téléphones"] if len(nb) < 14 or len(nb) > 17 and len(nb) > 4
    ]
    detected["Téléphones"] = [
        phone for phone in detected["Téléphones"] if 14 <= len(phone) <= 16
    ]

    print(f"Entités détectées: {[(k, len(v)) for k, v in detected.items()]}")
    return detected

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
        print("=== DÉBUT TRAITEMENT PDF ===")
        
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
        
        fake = faker.Faker()
        mode = request.form.get('mode', 'auto')
        print(f"Mode: {mode}")

        if mode == "manual":
            # Mode manuel
            words = json.loads(request.form.get('words', '[]'))
            print(f"Mots manuels: {words}")
            
            replacements = {word: generate_fake_value(word, fake) for word in words}
            mask_mode = request.form.get('optionManuel') == 'mask'
            
            print(f"Replacements: {len(replacements)}, Mask mode: {mask_mode}")
            replace_text_in_pdf(input_path, replacements, output_path, mask_mode)
        else:
            # Mode automatique ou filtré
            filters = json.loads(request.form.get('filters', '["names","phones","emails","iban","bic"]'))
            print(f"Filtres: {filters}")
            
            text = extract_text_from_pdf(input_path)
            if not text.strip():
                return jsonify({'error': 'Impossible d\'extraire le texte du PDF'}), 400
            
            print(f"Texte extrait: {len(text)} caractères")
            entities = detect_entities(text)

            replacements = {}
            for key, values in entities.items():
                if FILTER_MAP.get(key, key.lower()) not in filters:
                    print(f"Filtrage: {key} ignoré")
                    continue
                    
                for value in values:
                    try:
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
                    except Exception as e:
                        print(f"Erreur génération pour {value}: {e}")
                        replacements[value] = "#" * len(value)

            print(f"Total replacements: {len(replacements)}")
            replace_text_in_pdf(input_path, replacements, output_path)

        # Vérifier que le fichier de sortie existe
        if not os.path.exists(output_path):
            return jsonify({'error': 'Erreur lors de la génération du fichier anonymisé'}), 500
        
        print(f"=== SUCCÈS - Fichier généré: {output_path} ===")
        
        return send_file(
            output_path, 
            as_attachment=True, 
            download_name=f'anonymized_{filename}', 
            mimetype='application/pdf'
        )

    except Exception as e:
        error_msg = f"Erreur lors du traitement: {str(e)}"
        print(f"❌ {error_msg}")
        traceback.print_exc()
        return jsonify({'error': error_msg}), 500

    finally:
        # Nettoyage des fichiers temporaires
        for path in [input_path, output_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"Fichier supprimé: {path}")
                except Exception as e:
                    print(f"Erreur suppression {path}: {e}")

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'OK', 
        'spire_available': SPIRE_AVAILABLE,
        'pymupdf_available': PYMUPDF_AVAILABLE
    })

if __name__ == '__main__':
    print("=== DÉMARRAGE SERVEUR PDF ANONYMIZER ===")
    print(f"Spire.PDF disponible: {SPIRE_AVAILABLE}")
    print(f"PyMuPDF disponible: {PYMUPDF_AVAILABLE}")
    
    if not SPIRE_AVAILABLE and not PYMUPDF_AVAILABLE:
        print("⚠️  ATTENTION: Aucune bibliothèque PDF disponible!")
        print("Installez PyMuPDF: pip install PyMuPDF")
    
    app.run(debug=True, host='0.0.0.0', port=5000)