from flask import Flask, request, send_file, jsonify
from flask_cors import CORS  # Import CORS to handle cross-origin requests
import json
import os
import spacy
import re
from PyPDF2 import PdfReader
from spire.pdf import *
from werkzeug.utils import secure_filename
import faker
import random

app = Flask(__name__)

def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    full_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"
    return full_text

unique_cyrillic_letters = [ 'Ё', 'Ж', 'З', 'И', 'Й', 'Л', 'П', 'Ф', 'Ц', 'Ч', 'Ш', 'Щ', 'Ъ', 'Ы', 'Ь', 'Э', 'Ю', 'Я' ]

CORS(app)

UPLOAD_FOLDER = 'temp_uploads'
OUTPUT_FOLDER = 'temp_output'
ALLOWED_EXTENSIONS = {'pdf'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Utility function to check file type
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# API Endpoint to handle PDF anonymization
@app.route('/api/anonymize-pdf', methods=['POST'])
def anonymize_pdf():

    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type, only PDF allowed'}), 400
        
        filename = secure_filename(file.filename)
        input_pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        output_pdf_path = os.path.join(OUTPUT_FOLDER, f'anonymized_{filename}')
        file.save(input_pdf_path)
        fake = faker.Faker()
        
        email_pattern = r"\b[A-Za-z0-9.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        phone_pattern = r"\b(?:\+?\d{1,3}\s?)?(?:\(?\d{1,4}\)?\s?)?\d{1,4}(?:\s?\d{1,4}){1,3}\b"
        iban_pattern = r"[A-Z]{2}\d{2}\s?(?:\d{4}\s?){4,7}\d{1,4}"
        bic_pattern = r"[A-Z]{4}\s?\w{2}\s?\w{2}"
        
        if request.form['mode'] == "manual":
            words = json.loads(request.form['words'])
            listFake = []
            
            pdf = PdfDocument()
            pdf.LoadFromFile(input_pdf_path)
            
            for word in words:
                if re.match(iban_pattern, word):
                    iban = word[:2] + "".join(random.choice("0123456789") for _ in range(len(word) - 2))
                    listFake.append(str(iban))
                elif re.match(email_pattern, word):
                    words[words.index(word)] = word[0].lower() + word[1:] # car le site selectionne les emails avec une majuscule au début
                    listFake.append(fake.email())
                elif re.match(bic_pattern, word):
                    bic = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(len(word)))
                    listFake.append(str(bic))
                elif word[0].isupper():
                    nom = fake.name()
                    for chr in word:
                        if not chr.isalpha():
                            nom = nom + chr
                    listFake.append(str(nom))
                else:
                    fakeword = word[:2]
                    for i in range(2, len(word)):
                        if word[i].isdigit():
                            fakeword += str(random.randint(0, 9))
                        elif word[i].isalpha():
                            fakeword += str(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
                        else:
                            fakeword += word[i]
                    listFake.append(str(fakeword))
                    
            for i in range(pdf.Pages.Count):
                page = pdf.Pages.get_Item(i)
                replacer = PdfTextReplacer(page)
                for i in range (len(words)):
                  if(request.form['optionManuel'] == "mask"):
                    replacer.ReplaceAllText(words[i], "#" * (len(words[i])-2))
                  else:
                    replacer.ReplaceAllText(words[i], listFake[i])
            
            pdf.SaveToFile(output_pdf_path)
            pdf.Close()
            
            return send_file( # renvoyer le fichier anonymisé
                output_pdf_path,
                as_attachment=True,
                download_name='anonymized.pdf',
                mimetype='application/pdf'
            )
            
        else : 
            all_filt = {
                "names": "Noms",
                "phones": "Téléphones",
                "emails": "Emails",
                "iban": "IBANs",
                "bic": "BICs",
            }
            filters = ["names","phones","emails","iban","bic"]
            if request.form["mode"] == "filter":
                filters = json.loads(request.form['filters'])

            try:
                text = extract_text_from_pdf(input_pdf_path)
                print("Texte extrait du PDF:")
            except Exception as e:
                print(f"Une erreur est survenue : {str(e)}")

            nlp = spacy.load("fr_core_news_sm")
            
            name_pattern = r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b"

            doc = nlp(text)

            detected_entities = {
                "Noms": [],
                "Emails": [],
                "Téléphones": [],
                "Nombres": [],
                "IBANs": [],
                "BICs": [],
            }

            for ent in doc.ents:
                if ent.label_ == "PER" and ent.text not in detected_entities["Noms"]:
                    detected_entities["Noms"].append(ent.text)

            regex_names = re.findall(name_pattern, text)
            for name in regex_names:
                if name not in detected_entities["Noms"] and name.lower() not in [
                    "date",
                    "cordialement",
                    "siret",
                    "mail",
                    "mode",
                    "conditions",
                    "nous",
                    "au",
                    "intracom",
                    "code",
                ]:
                    sep_new_line = name.split("\n")
                    for name in sep_new_line:
                        if name not in detected_entities["Noms"]:
                            detected_entities["Noms"].append(name)

            detected_entities["Noms"] = [ent for ent in detected_entities["Noms"] if len(ent) > 2]

            texte_coupe_a_bic = text.split("BIC")

            detected_entities["Emails"] = re.findall(email_pattern, text)
            detected_entities["Téléphones"] = re.findall(phone_pattern, text)
            allTel = detected_entities["Téléphones"]
            detected_entities["Téléphones"] = [
                phone for phone in allTel if len(phone) >= 14 and len(phone) <= 16
            ]
            detected_entities["Nombres"] = [
                nb for nb in allTel if (len(nb) < 14 or len(nb) > 17) and len(nb) > 4
            ]
            detected_entities["IBANs"] = re.findall(iban_pattern, text)
            for elt in texte_coupe_a_bic[1:]:
                detected_entities["BICs"].append(re.findall(bic_pattern, elt)[0])

            fake = faker.Faker()


            bic = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(8))

            pdf = PdfDocument()

            pdf.LoadFromFile(input_pdf_path)
            
            for key, val in all_filt.items():
                if key not in filters:
                    detected_entities[val] = []
                    
            print("Résultats détectés :")
            for category, entities in detected_entities.items():
                print(f"{category} : {entities}")

            for i in range(pdf.Pages.Count):
                page = pdf.Pages.get_Item(i)

                replacer = PdfTextReplacer(page)

                for category, entities in detected_entities.items():
                    if category == "Noms":
                        for entity in entities:
                            nom = fake.name().split(" ")[0]
                            for chr in entity:
                                if chr.upper() in unique_cyrillic_letters:
                                    nom += random.choice(unique_cyrillic_letters)
                                elif not chr.isalpha():
                                    nom = nom + chr
                            replacer.ReplaceAllText(entity, nom)
                    elif category == "Téléphones":
                        for entity in entities:
                            tel = ''
                            for elt in entity:
                                if not elt.isdigit():
                                    tel += elt
                                else:
                                    tel += str(random.randint(0, 9))
                            replacer.ReplaceAllText(entity[5:], tel[5:])
                    elif category == "Nombres":
                        for entity in entities:
                            replacer.ReplaceAllText(
                                entity,
                                str(random.randint(10 ** (len(entity) - 1), 10 ** len(entity) - 1)),
                            )
                    elif category == "Emails":
                        for entity in entities:
                            mail = fake.email()
                            replacer.ReplaceAllText(entity.split("@")[0], mail.split("@")[0])
                    elif category == "IBANs":
                        for entity in entities:
                            iban = fake.iban()
                            replacer.ReplaceAllText(entity[2:], iban[2:])
                    elif category == "BICs":
                        for entity in entities:
                            replacer.ReplaceAllText(entity, bic)

            pdf.SaveToFile(output_pdf_path)
            pdf.Close()

            return send_file( # renvoyer le fichier anonymisé
                output_pdf_path,
                as_attachment=True,
                download_name='anonymized.pdf',
                mimetype='application/pdf'
            )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        # supprimer les fichiers temporaires
        if 'input_pdf_path' in locals():
            try:
                os.remove(input_pdf_path)
            except:
                pass
        if 'output_pdf_path' in locals():
            try:
                os.remove(output_pdf_path)
            except:
                pass

if __name__ == '__main__':
    app.run(debug=True)