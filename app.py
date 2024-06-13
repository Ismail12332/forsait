import os
from flask import Flask, render_template, request, redirect, url_for, session,jsonify,abort,send_file, make_response
from pymongo import MongoClient
from passlib.hash import bcrypt
from bson import ObjectId
from datetime import datetime
from dotenv import load_dotenv
from flask_cors import CORS,cross_origin
from urllib.parse import quote
from b2sdk.v2 import *
import secrets
import uuid
import pprint
import jwt
import requests
from jose import jwt, JWTError
from functools import wraps
from openai import OpenAI
import traceback
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Indenter, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.graphics.shapes import Drawing, Line
from reportlab.lib.units import inch
from reportlab.lib import colors
from io import BytesIO
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import html
import time
import stripe
import io
import random
import string
import boto3
import qrcode
from PIL import Image
import logging

load_dotenv()

def create_app():
    class User:
        def __init__(self, username, password, email):
            self.username = username
            self.password_hash = bcrypt.hash(password)
            self.email = email



    app = Flask(__name__, template_folder='templates')
    CORS(app, supports_credentials=True)
    app.secret_key = secrets.token_hex(32)
    client = MongoClient(os.getenv("MONGODB_URI"))
    app.db = client.my_database
    users_collection = app.db.users
    projects_collection = app.db.projects
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY")
    )

    # Создание клиента Backblaze B2
    info = InMemoryAccountInfo()
    b2_api = B2Api(info)
    application_key_id = '4ad4332a1370'
    application_key = '004787d4a1ca0ed42646b85d3f9cf9523f3c5847a4'
    b2_api.authorize_account("production", application_key_id, application_key)

    # Получение бакета (папки) для хранения изображений
    bucket_name_b2 = 'Survzila'
    bucket = b2_api.get_bucket_by_name(bucket_name_b2)

    # Регистрация шрифта
    pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))


    # Конфигурация Auth0
    AUTH0_DOMAIN = 'dev-whbba5qnfveb88fc.us.auth0.com'
    API_AUDIENCE = 'http://Survzilla'
    ALGORITHMS = ['RS256']


    # Получение открытых ключей Auth0 с обработкой ошибок
    jwks_url = f'https://{AUTH0_DOMAIN}/.well-known/jwks.json'

    # Vultr Object Storage Configuration
    VULTR_ACCESS_KEY = os.getenv('VULTR_ACCESS_KEY_API')
    VULTR_SECRET_KEY = os.getenv('VULTR_SECRET_KEY_API')
    VULTR_ENDPOINT_URL = 'https://ewr1.vultrobjects.com'  # Replace with your region's endpoint

    s3_client = boto3.client(
        's3',
        endpoint_url=VULTR_ENDPOINT_URL,
        aws_access_key_id=VULTR_ACCESS_KEY,
        aws_secret_access_key=VULTR_SECRET_KEY
    )

    BUCKET_NAME = 'verboatimg'

    def get_jwks():
        for attempt in range(3):  # Попробуем три раза
            try:
                jwks = requests.get(jwks_url).json()
                return jwks
            except requests.exceptions.ConnectionError as e:
                print(f"Ошибка соединения при попытке {attempt + 1}: {e}")
                time.sleep(1)  # Подождем секунду перед повторной попыткой
        raise RuntimeError("Не удалось получить JWKS ключи после нескольких попыток")

    jwks = get_jwks()

    def get_rsa_key(header):
        for key in jwks['keys']:
            if key['kid'] == header['kid']:
                return {
                    'kty': key['kty'],
                    'kid': key['kid'],
                    'use': key['use'],
                    'n': key['n'],
                    'e': key['e']
                }
        return None

    def requires_auth(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth_header = request.headers.get('Authorization', None)
            if not auth_header:
                return jsonify({"message": "Authorization header is missing"}), 401

            token = auth_header.split()[1]
            try:
                header = jwt.get_unverified_header(token)
                rsa_key = get_rsa_key(header)
                if not rsa_key:
                    return jsonify({"message": "Invalid header"}), 401

                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=ALGORITHMS,
                    audience=API_AUDIENCE,
                    issuer=f'https://{AUTH0_DOMAIN}/'
                )
            except JWTError as e:
                return jsonify({"message": "Invalid token"}), 401

            request.user = payload
            return f(*args, **kwargs)
        return decorated



    @app.route("/", methods=["GET"])
    def login(supports_credentials=True):
        return render_template("index.html")
    

    @app.route("/api/vitrine", methods=["GET"])
    def get_vitrine_projects():
        try:
            projects = list(app.db.vitrine.find({}))
            for project in projects:
                project['_id'] = str(project['_id'])
                project['project_id'] = str(project['project_id'])
            return jsonify({"status": "success", "projects": projects}), 200
        except Exception as e:
            print(f"Произошла ошибка: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    

    #выход
    @app.route("/logout")
    def logout():
        # Очищаем сессию пользователя при выходе
        session.pop("user_id", None)
        return redirect(url_for("login"))


    def create_project_pdf(project):
        buffer = BytesIO()
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='CustomNormal', fontName='DejaVuSans'))
        styles.add(ParagraphStyle(name='CenteredHeading1', parent=styles['Heading1'], alignment=1))

        def build_story(project):
            story = []

            # Добавление основной информации проекта
            Survey_logo = "static/images/survz.webp"
            img = Image(Survey_logo)
            img.drawHeight = 2 * inch
            img.drawWidth = 2 * inch
            story.append(img)

            # Обработка first_name и last_name
            first_name = project['first_name'] or ''
            last_name = project['last_name'] or ''

            F_L_Name = first_name + " " + last_name
            story.append(Paragraph(f"Survzilla Survey Report for {F_L_Name}", styles['CenteredHeading1']))
            story.append(Paragraph(f"Vessel - {project['vessel_name']}", styles['CenteredHeading1']))

            gen_info_images = project['sections']['introduction']['gen_info'].get('images', [])
            if gen_info_images:
                intro_image_url = gen_info_images[0]
                intro_image = Image(intro_image_url)
                intro_image.drawHeight = 5 * inch
                intro_image.drawWidth = 5 * inch
                story.append(intro_image)
            story.append(Spacer(1, 0.2 * inch))
            story.append(PageBreak())

            for section_name, section_content in project['sections'].items():
                # Проверка, есть ли в подразделах непустые данные
                has_non_empty_subsection = False
                for subsection_name, subsection_content in section_content.items():
                    if subsection_content['steps'] or subsection_content['images']:
                        has_non_empty_subsection = True
                        break
                
                if not has_non_empty_subsection:
                    continue  # Пропускаем этот раздел, если все его подразделы пусты

                cleaned_section_name = section_name.replace('_', ' ').title()
                story.append(Paragraph(cleaned_section_name, styles['CenteredHeading1']))

                for subsection_name, subsection_content in section_content.items():
                    if subsection_content['steps'] or subsection_content['images']:
                        cleaned_subsection_name = subsection_name.replace('_', ' ').title()
                        criticality = subsection_content.get('criticality', '')
                        crit_img_path = f"static/images/{criticality}.png" if criticality else None
                        crit_img = Image(crit_img_path) if crit_img_path else None
                        if crit_img:
                            crit_img.drawHeight = 0.3 * inch
                            crit_img.drawWidth = 0.3 * inch
                            subsection_paragraph = Paragraph(f"{cleaned_subsection_name}&nbsp;&nbsp;", styles['CustomNormal'])
                            subsection_table = Table([[subsection_paragraph, crit_img]], colWidths=[2 * inch, 0.5 * inch])
                            story.append(subsection_table)
                        else:
                            story.append(Paragraph(cleaned_subsection_name, styles['CustomNormal']))

                        images = []
                        for image_url in subsection_content['images']:
                            img = Image(image_url)
                            img.drawHeight = 2 * inch
                            img.drawWidth = 2 * inch
                            images.append(img)
                            if len(images) == 2:
                                story.append(Table([images], colWidths=[2.5 * inch, 2.5 * inch]))
                                story.append(Spacer(1, 0.2 * inch))
                                images = []
                        if images:
                            story.append(Table([images], colWidths=[2.5 * inch, 2.5 * inch]))
                            story.append(Spacer(1, 0.2 * inch))

                        story.append(Indenter(left=20))


                        
                        
                        
                        for step in subsection_content['steps']:
                            step = html.escape(step)
                            story.append(Paragraph(step, styles['CustomNormal']))
                            story.append(Spacer(1, 0.1 * inch))
                        story.append(Indenter(left=-20))

                story.append(Spacer(0.5, 0.2 * inch))
                story.append(Spacer(1, 0.2 * inch))
                story.append(Spacer(0.5, 0.2 * inch))

            return story

        # Создаем временный PDF для определения общего количества страниц
        temp_buffer = BytesIO()
        temp_doc = SimpleDocTemplate(temp_buffer, pagesize=letter)
        story = build_story(project)
        temp_doc.build(story)
        total_pages = temp_doc.page

        # Создаем основной PDF с нумерацией страниц
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)

        def on_first_page(canvas, doc):
            page_num = canvas.getPageNumber()
            text = f"{project['vessel_name']} inspected by Survzilla Boat Inspection page {page_num} of {total_pages}"
            canvas.setFont('Helvetica', 10)
            canvas.drawRightString(doc.width + doc.rightMargin, 0.75 * inch, text)

        def on_later_pages(canvas, doc):
            page_num = canvas.getPageNumber()
            text = f"'{project['vessel_name']}' inspected by Survzilla Boat Inspection page {page_num} of {total_pages}"

            canvas.setFont('Helvetica-Bold', 12)
            canvas.drawString(doc.leftMargin, doc.height + doc.topMargin + 35, project['vessel_name'])
            canvas.setStrokeColor(colors.black)
            canvas.setLineWidth(0.5)
            canvas.line(doc.leftMargin, doc.height + doc.topMargin + 25, doc.width + doc.leftMargin, doc.height + doc.topMargin + 25)
            canvas.line(doc.leftMargin, doc.height + doc.topMargin + 27, doc.width + doc.leftMargin, doc.height + doc.topMargin + 27)

            canvas.setFont('Helvetica', 10)
            canvas.drawRightString(doc.width + doc.rightMargin, 0.75 * inch, text)

        story = build_story(project)
        doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
        buffer.seek(0)
        return buffer


    @app.route('/download_project_pdf/<project_id>')
    @requires_auth
    def download_project_pdf(project_id):
        # Получение проекта по его ID (примерная реализация)
        project = projects_collection.find_one({"_id": ObjectId(project_id)})

        if not project:
            abort(404, description="Project not found")

        pdf_buffer = create_project_pdf(project)

        # Отправка PDF клиенту
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=f"project_{project_id}.pdf",
            mimetype='application/pdf'
        )

    def convert_projects_to_list(projects):
        #Converts MongoDB projects to a list with ObjectId converted to string.
        projects_list = []
        for project in projects:
            project_data = {**project}
            project_data["_id"] = str(project["_id"])
            projects_list.append(project_data)
        return projects_list
    

    @app.route("/api/glav", methods=["GET"])
    @requires_auth
    def get_projects(supports_credentials=True):
        user_id = request.user.get('sub')  # Извлекаем user_id из токена
        projects = app.db.projects.find({"user_id": user_id})
        projects_list = convert_projects_to_list(projects)
        return jsonify({"status": "success", "user_id": str(user_id), "projects": projects_list})
    

    @app.route("/main", methods=["GET"])
    def get_projectse(supports_credentials=True):
            return render_template("index.html")
    

    @app.route("/cheakglav", methods=["GET"])
    @requires_auth
    def go_to_glav(supports_credentials=True):
            return jsonify({"status": "success"})


    @app.route("/index2", methods=["POST"])
    @requires_auth
    def create_project():
        user_id = request.user.get("sub")
        data = request.json  # Получаем данные из JSON-запроса
        # Обновляем запрос к базе данных, чтобы фильтровать проекты по user_id
        projects = app.db.projects.find({"user_id": user_id})
        projects_list = convert_projects_to_list(projects)

        boat_make = data.get('boat_make')
        boat_model = data.get('boat_model')
        boat_registration = data.get('boat_registration')
        length = data.get('length')
        year = data.get('year')
        engine = data.get('engine')
        price = data.get('price')
        city = data.get('city')
        owner_contact = data.get('owner_contact')
        project_code = generate_unique_code(app.db.projects)

        # Создаем проект
        project = {
            'user_id': user_id,
            'boat_make': boat_make,
            'boat_model': boat_model,
            'boat_registration': boat_registration,
            'length': length,
            'year': year,
            'engine': engine,
            'price': price,
            'city': city,
            'owner_contact': owner_contact,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_code": project_code,
            "sections": {
                    "Introduction": {"Gen_info": {},"certification": {},"purpose_of_survey": {},"circumstances_of_survey": {},"report_file_no": {},"surveyor_qualifications": { },"intended_use": {},
                    },
                    "Hull": { "layout_overview": {},"design": {},"deck": {},"structural_members": {},"bottom_paint": {},"blister_comment": {},"transom": {},
                    },
                    "Above": { "deck_floor_plan": {},"anchor_platform": {},"toe_rails": {},"mooring_hardware": {},"hatches": {},"exterior_seating": {},"cockpit_equipment": {},"ngine_hatch": {},"above_draw_water_line": {},"boarding_ladder": {},"swim_platform": {},
                    },
                    "Below": { "below_draw_water": {},"thru_hull_strainers": {},"transducer": {},"sea_valves": {},"sea_strainers": {},"trim_tabs": {},"note": {},
                    },
                    "Cathodic": { "bonding_system": {},"anodes": {},"lightning_protection": {},"additional_remarks": {},
                    },
                    "Helm": { "helm_station": {},"throttle_shift_controls": {},"engine_room_blowers": {},"engine_status": {},"other_electronics_controls": {},
                    },
                    "Cabin": { "entertainment_berthing": {},"interior_lighting": {},"galley_dinette": {},"water_closets": {},"climate_control": {},
                    },
                    "Electrical": { "dc_systems_type": {},"ac_systems": {},"generator": {},
                    },
                    "Inboard": { "engines": {},"serial_numbers": {},"engine_hours": {},"other_note": {},"reverse_gears": {},"shafting_propellers": {},
                    },
                    "Steering": { "manufacture": {},"steering_components": {},
                    },
                    "Tankage": { "fuel": {},"potable_water_system": {},"holding_tank_black_water": {},
                    },
                    "Safety": { "navigational_lights": {},"life_jackets": {},"throwable_pfd": {},"visual_distress_signals": {},"sound_devices": {},"uscg_placards": {},"flame_arrestors": {},"engine_ventilation": {},"ignition_protection": {},"inland_navigational_rule_book": {},"waste_management_plan": {},"fire_fighting_equipment": {},"bilge_pumps": {},"ground_tackle_windlass": {},"auxiliary_safety_equipment": {},
                    },
                }
        }

        result = app.db.projects.insert_one(project)
        project_id = result.inserted_id

        print("Entry added:", boat_make, boat_model, city, boat_registration, length, engine, user_id, project_id,price)
        return jsonify({"status": "success", "user_id": str(user_id), "project_id": str(project_id)})



    def generate_random_code(length=8):
        characters = string.ascii_uppercase + string.digits
        return ''.join(random.choice(characters) for _ in range(length))

    def generate_unique_code(collection, length=8):
        while True:
            code = generate_random_code(length)
            if not collection.find_one({"project_code": code}):
                return code



    # Проверка, что текущий пользователь является владельцем проекта
    def check_project_owner(user_id, project_id):
        project = app.db.projects.find_one({"_id": ObjectId(project_id), "user_id": user_id})
        return project is not None


    @app.route("/api/update_criticality", methods=["POST"])
    @requires_auth
    def update_criticality():
        user_id = request.user.get('sub')
        data = request.get_json()
        section = data.get('section')
        subsection = data.get('subsection')
        element = data.get('element')
        criticality = data.get('criticality')
        project_id = ObjectId(data.get('project_id'))

        # Проверка подлинности клиента
        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        if not section or not subsection or not element or not criticality:
            return jsonify({"message": "Missing data"}), 400

        # Обновление критичности в элементе
        result = app.db.projects.update_one(
            {"_id": project_id, "user_id": user_id},
            {"$set": {f"sections.{section}.{subsection}.{element}.criticality": criticality}}
        )

        if result.modified_count == 1:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"message": "Failed to update criticality"}), 400


    #Переключение на проект в главное странице нажатие на имя проекта
    @app.route("/api/EditProject/<string:project_id>", methods=["POST"])
    @requires_auth
    def edit_project(project_id,supports_credentials=True):
        user_id = request.user.get('sub')

        #Проверка подлености клиента
        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        try:
            # Преобразовываем project_id в ObjectId
            project_id = ObjectId(project_id)
        except Exception as e:
            # Обработка ошибки, если project_id неверного формата
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        # Проверяем, что текущий пользователь имеет доступ к проекту
        project = app.db.projects.find_one({"_id": project_id})
        if project is None:
            return jsonify({"status": "error", "message": "Project not found"}), 404

        project['_id'] = str(project['_id'])
        # Возвращаем данные о проекте в формате JSON
        print(f"Fetching project with ID: {project_id}", project)

        return jsonify({"status": "success", "project": project})


    @app.route("/EditProject/<project_id>", methods=["GET"])
    def get_projectse_edit_project(project_id,supports_credentials=True):
        return render_template("index.html")


    #Дабовление и удаление записей в разделах 
    @app.route("/edit_project/<project_id>/add_step", methods=["POST"])
    @requires_auth
    def add_step(project_id):
        user_id = request.user.get('sub')

        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        data = request.json
        section = data.get("section")
        subsection = data.get("subsection")
        element = data.get("element")
        step_description = data.get("step_description")
        print(section,subsection,element,step_description)

        try:
            result = app.db.projects.update_one(
                {"_id": project_id, f"sections.{section}.{subsection}.{element}": {"$exists": True}},
                {"$push": {f"sections.{section}.{subsection}.{element}.steps": step_description}}
            )

            if result.modified_count == 0:
                return jsonify({"status": "error", "message": "Project, section, subsection or element not found"}), 404

            updated_project = app.db.projects.find_one({"_id": project_id})
            updated_project["_id"] = str(updated_project["_id"])

            return jsonify({"status": "success", "message": "Step added successfully", "updated_project": updated_project})
        except Exception as e:
            print("Error:", e)
            return jsonify({"status": "error", "message": "An error occurred"}), 500

    
    

    #Добавление изображения в основные подразделы (нужно переделать)-----------------------------------------
    @app.route('/edit_project/<project_id>/add_image', methods=['POST'])
    @requires_auth
    def add_image(project_id):
        user_id = request.user.get('sub')

        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        if 'image_upload' not in request.files:
            return jsonify({"status": "error", "message": "No file part"}), 400

        image_file = request.files['image_upload']

        if image_file.filename == '':
            return jsonify({"status": "error", "message": "No selected file"}), 400

        if image_file:
            file_data = image_file.read()
            file_name = image_file.filename
            s3_file_name = str(uuid.uuid4())

            try:
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=s3_file_name,
                    Body=file_data,
                    ContentType=image_file.content_type,
                    ACL='public-read'  # Make the object publicly accessible
                )

                file_info = {
                    'file_name': file_name,
                    's3_file_name': s3_file_name,
                    's3_url': f'{VULTR_ENDPOINT_URL}/{BUCKET_NAME}/{quote(s3_file_name)}'
                }
                app.db.files.insert_one(file_info)

                section = request.form.get('section')
                subsection = request.form.get("subsection")
                element = request.form.get("element")

                app.db.projects.update_one(
                    {"_id": project_id, f"sections.{section}.{subsection}.{element}": {"$exists": True}},
                    {"$push": {f"sections.{section}.{subsection}.{element}.images": file_info["s3_url"]}}
                )

                updated_project = app.db.projects.find_one({"_id": project_id})
                updated_project["_id"] = str(updated_project["_id"])

                return jsonify({
                    "status": "success",
                    "message": "Image uploaded successfully",
                    "updated_project": updated_project
                }), 200
            except Exception as e:
                return jsonify({"status": "error", "message": "Failed to upload file"}), 500
        else:
            return jsonify({"status": "error", "message": "Failed to upload file"}), 400
        

    @app.route("/edit_project/<project_id>/remove_image", methods=["POST"])
    @requires_auth
    def remove_image(project_id):
        user_id = request.user.get('sub')

        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        data = request.json
        section = data.get("section")
        subsection = data.get("subsection")
        element = data.get("element")
        image = data.get("image")

        try:
            result = app.db.projects.update_one(
                {"_id": project_id, f"sections.{section}.{subsection}.{element}.images": image},
                {"$pull": {f"sections.{section}.{subsection}.{element}.images": image}}
            )

            if result.modified_count == 0:
                return jsonify({"status": "error", "message": "Image not found"}), 404

            updated_project = app.db.projects.find_one({"_id": project_id})
            updated_project["_id"] = str(updated_project["_id"])

            return jsonify({"status": "success", "message": "Image removed successfully", "updated_project": updated_project})
        except Exception as e:
            print("Error:", e)
            return jsonify({"status": "error", "message": "An error occurred"}), 500


    @app.route("/edit_project/<project_id>/remove_step", methods=["POST"])
    @requires_auth
    def remove_step(project_id):
        user_id = request.user.get('sub')

        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        data = request.json
        section = data.get("section")
        subsection = data.get("subsection")
        element = data.get("element")
        step_description = data.get("step_description")
        print(section,subsection,element,step_description)
        

        try:
            result = app.db.projects.update_one(
                {"_id": project_id, f"sections.{section}.{subsection}.{element}.steps": step_description},
                {"$pull": {f"sections.{section}.{subsection}.{element}.steps": step_description}}
            )

            if result.modified_count == 0:
                return jsonify({"status": "error", "message": "Step not found"}), 404

            updated_project = app.db.projects.find_one({"_id": project_id})
            updated_project["_id"] = str(updated_project["_id"])

            return jsonify({"status": "success", "message": "Step removed successfully", "updated_project": updated_project})
        except Exception as e:
            print("Error:", e)
            return jsonify({"status": "error", "message": "An error occurred"}), 500


    #----------------------------------------------------------------
    #Добавление раздела
    @app.route("/edit_project/<project_id>/add_section", methods=["POST"])
    @requires_auth
    def add_section(project_id):
        user_id = request.user.get('sub')

        #Проверка подлености клиента
        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403
        

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return "Invalid project_id", 400

        section_name = request.form.get("section_name")

        try:
            result = app.db.projects.update_one(
                {"_id": project_id},
                {"$set": {f"sections.{section_name}": {}}}
            )
            if result.modified_count == 0:
                return "Project not found", 404
        except Exception as e:
            print("Error:", e)
            return "An error occurred", 500
        updated_project = app.db.projects.find_one({"_id": project_id})
        updated_project['_id'] = str(updated_project['_id'])
        
        return jsonify({"status": "success", "message": "Section added successfully", "updated_project": updated_project})


    #Добавление подраздела
    @app.route("/edit_project/<project_id>/add_subsection", methods=["POST"])
    @requires_auth
    def add_subsection(project_id):
        user_id = request.user.get('sub')

        #Проверка подлености клиента
        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403
        

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        data = request.json
        section_name = data.get("section_name")
        subsection_name = data.get("subsection_name")
        print(section_name,subsection_name)

        if not section_name or not subsection_name:
            return jsonify({"status": "error", "message": "Section name and Subsection name are required"}), 400

        try:
            # Добавляем новый подраздел в выбранный раздел
            result = app.db.projects.update_one(
                {"_id": project_id},
                {"$set": {f"sections.{section_name}.{subsection_name}": {}}}
            )
            if result.modified_count == 0:
                return jsonify({"status": "error", "message": "Project or section not found"}), 404
        except Exception as e:
            print("Error:", e)
            return jsonify({"status": "error", "message": "An error occurred during subsection addition"}), 500

        updated_project = app.db.projects.find_one({"_id": project_id})
        updated_project['_id'] = str(updated_project['_id'])
        
        return jsonify({"status": "success", "message": "Subsection added successfully", "updated_project": updated_project})
    

    #чат джипити
    @app.route('/edit_project/<project_id>/get-gpt-recommendations', methods=['POST'])
    @requires_auth
    def get_gpt_recommendations(project_id):
        user_id = request.user.get('sub')

        #Проверка подлености клиента
        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403
        
        data = request.json
        section = data['section']
        subsection = data['subsection']
        description = data['step_description']
        prompt = f"part of the ship was inspected {section}, namely, looked around{subsection}. in short then {description}"

        try:
            response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an assistant to an employee who inspects yachts, he writes you a brief description of the inspection of a certain part of the ship (let’s assume everything is fine), you need to describe how the inspection was carried out"},
                {"role": "user", "content": prompt}
            ]
            )
            print(response)
            recommendations = response.choices[0].message.content.strip()
            return jsonify({'recommendations': recommendations})
        except Exception as e:
            print(f"Произошла ошибка: {e}")
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
            


    @app.route("/api/add_to_showcase", methods=["POST"])
    @requires_auth
    def add_to_showcase():
        try:
            user_id = request.user.get('sub')  # Extract user_id from token
            data = request.form.to_dict()
            project_id = ObjectId(data.get('project_id'))
            price = data.get('price')
            description = data.get('description')
            final_note = data.get('final_note')
            file = request.files.get('file')
            final_kartinka = request.files.get('final_kartinka')

            logging.debug(f"Received data: {data}")
            logging.debug(f"Received files: file={file}, final_kartinka={final_kartinka}")

            if not check_project_owner(user_id, project_id):
                return jsonify({"status": "error", "message": "Unauthorized access"}), 403

            if not project_id or not price or not description or not file or not final_note or not final_kartinka:
                return jsonify({"message": "Missing project_id, price, description, file, final_note, or final_kartinka"}), 400

            project = app.db.projects.find_one({"_id": project_id, "user_id": user_id})
            if not project:
                return jsonify({"message": "Project not found"}), 404

            # Upload the files to Vultr Object Storage
            s3_file_name = str(uuid.uuid4())
            final_kartinka_name = str(uuid.uuid4())

            try:
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=s3_file_name,
                    Body=file.read(),
                    ContentType=file.content_type,
                    ACL='public-read'  # Make the object publicly accessible
                )
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=final_kartinka_name,
                    Body=final_kartinka.read(),
                    ContentType=final_kartinka.content_type,
                    ACL='public-read'  # Make the object publicly accessible
                )

                file_info = {
                    's3_url': f'{VULTR_ENDPOINT_URL}/{BUCKET_NAME}/{quote(s3_file_name)}'
                }

                final_kartinka_info = {
                    's3_url': f'{VULTR_ENDPOINT_URL}/{BUCKET_NAME}/{quote(final_kartinka_name)}'
                }

                # Generate QR Code with logo in the center
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_H,
                    box_size=10,
                    border=4,
                )
                project_url = f"https://verboat.com/yachtpreview/{project['project_code']}"
                qr.add_data(project_url)
                qr.make(fit=True)

                img = qr.make_image(fill='black', back_color='white').convert('RGB')

                # Load the logo and resize it
                logo = Image.open('static/images/VerboatLogo02.png')  # Update the path to your logo image
                logo_size = (img.size[0] // 4, img.size[1] // 4)
                logo = logo.resize(logo_size, Image.LANCZOS)

                # Calculate the position and paste the logo on the QR code
                logo_pos = ((img.size[0] - logo_size[0]) // 2, (img.size[1] - logo_size[1]) // 2)
                img.paste(logo, logo_pos, logo)

                buffered = BytesIO()
                img.save(buffered, format="PNG")
                qr_code_data = buffered.getvalue()

                # Upload QR Code to Vultr Object Storage
                qr_code_file_name = f"{project['project_code']}_qr.png"
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=qr_code_file_name,
                    Body=qr_code_data,
                    ContentType='image/png',
                    ACL='public-read'  # Make the object publicly accessible
                )
                qr_code_info = {
                    's3_url': f'{VULTR_ENDPOINT_URL}/{BUCKET_NAME}/{quote(qr_code_file_name)}'
                }

                # Check if the product already exists in Stripe
                existing_product = None
                try:
                    search_result = stripe.Product.search(
                        query=f"name:'{project['project_code']}'"
                    )
                    if search_result['data']:
                        existing_product = search_result['data'][0]
                except Exception as e:
                    logging.error(f"Failed to search Stripe products: {str(e)}")
                    return jsonify({"status": "error", "message": f"Failed to search Stripe products: {str(e)}"}), 500

                if not existing_product:
                    # Create Stripe product if it doesn't exist
                    stripe_product = stripe.Product.create(
                        name=f"{project['project_code']}",
                        description=description,
                        images=[file_info['s3_url']],
                    )

                    stripe_price = stripe.Price.create(
                        product=stripe_product.id,
                        unit_amount=1000,
                        currency='usd',
                    )
                else:
                    stripe_product = existing_product
                    stripe_price = stripe.Price.list(product=stripe_product.id, limit=1).data[0]

                vitrine_data = {
                    "vessel_name": f"{project['boat_make']} {project['boat_model']} {project['boat_registration']}",
                    "gen_info_image": file_info["s3_url"],
                    "user_id": user_id,
                    "project_id": project_id,
                    "price": price,
                    "city": project['city'],
                    "description": description,
                    "year": project['year'],
                    "project_code": project['project_code'],  # Добавляем код проекта
                    "access_list": [user_id],
                    "final_kartinka": final_kartinka_info["s3_url"],
                    "length": project['length'],
                    "qr_code": qr_code_info["s3_url"],
                    "stripe_product_id": stripe_product.id,
                    "stripe_price_id": stripe_price.id,  # Добавляем URL QR-кода
                }

                project_update_data = {
                    "final_note": final_note,
                    "final_kartinka": final_kartinka_info["s3_url"],
                    "description": description,
                    "main_image": file_info["s3_url"],
                    "qr_code": qr_code_info["s3_url"],
                    "stripe_product_id": stripe_product.id,
                    "stripe_price_id": stripe_price.id,
                }

                # Update the project with final_note, final_kartinka, description, and main_image
                app.db.projects.update_one(
                    {"_id": project_id},
                    {"$set": project_update_data}
                )

                existing_entry = app.db.vitrine.find_one({"project_id": project_id})
                if existing_entry:
                    result = app.db.vitrine.update_one(
                        {"project_id": project_id},
                        {"$set": vitrine_data}
                    )
                    if result.modified_count > 0:
                        return jsonify({"status": "success", "message": "Project updated in showcase"}), 200
                    else:
                        return jsonify({"message": "Failed to update project in showcase"}), 400
                else:
                    result = app.db.vitrine.insert_one(vitrine_data)
                    if result.inserted_id:
                        return jsonify({"status": "success", "message": "Project added to showcase"}), 200
                    else:
                        return jsonify({"message": "Failed to add project to showcase"}), 400
            except Exception as e:
                logging.error(f"Failed to upload file: {str(e)}")
                return jsonify({"status": "error", "message": f"Failed to upload file: {str(e)}"}), 500
        except Exception as e:
            logging.error(f"Failed to process request: {str(e)}")
            return jsonify({"status": "error", "message": f"Failed to process request: {str(e)}"}), 500
            


    @app.route("/yachtpreview/<project_id>", methods=["GET"])
    def yeacht_project(project_id):
        return render_template("index.html")
    
    
    @app.route("/viewproject/<project_id>", methods=["GET"])
    def yview_project(project_id):
        return render_template("index.html")


    #предварительной просмотр проекта
    @app.route("/api/preview/<project_code>", methods=["GET"])
    def preview_project_by_code(project_code):
        project = app.db.vitrine.find_one({"project_code": project_code})
        if not project:
            return jsonify({"status": "error", "message": "Project not found"}), 404

        # Convert ObjectId to string for JSON serialization
        project["_id"] = str(project["_id"])
        project["project_id"] = str(project["project_id"])
        return jsonify({"status": "success", "project": project}), 200
        

    #Просмотр проектов с ветрины
    @app.route("/api/project/<project_id>", methods=["GET"])
    @requires_auth
    def get_project(project_id):
        user_id = request.user.get('sub')  # Extract user_id from token

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        project_vitrine = app.db.vitrine.find_one({"project_id": project_id})
        if not project_vitrine:
            return jsonify({"status": "error", "message": "Project not found"}), 404
        
        # Check if the user is in the access_list
        if user_id not in project_vitrine.get("access_list", []):
            return jsonify({"status": "error", "message": "Access denied"}), 403

        project = app.db.projects.find_one({"_id": project_id})
        if not project:
            return jsonify({"status": "error", "message": "Project not found"}), 404

        project["_id"] = str(project["_id"])
        return jsonify({"status": "success", "project": project}), 200


    
    stripe.api_key = os.getenv("STRIPE_PK")
    endpoint_secret = os.getenv('STRIPE_WEBHOOK')

    @app.route("/api/check_access/<project_id>", methods=["GET"])
    @requires_auth
    def check_access(project_id):
        user_id = request.user.get('sub')  # Extract user_id from token
        project_id = ObjectId(project_id)

        project = app.db.vitrine.find_one({"project_id": project_id})
        if not project:
            return jsonify({"message": "Project not found"}), 404

        if user_id in project.get("access_list", []):
            return jsonify({"access": True}), 200

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': project['stripe_price_id'],
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'https://verboat.com/viewproject/{project_id}',
            cancel_url="https://verboat.com/",
            metadata={
                'user_id': user_id,
                'project_id': str(project_id)
            }
        )

        return jsonify({"access": False, "sessionId": session.id}), 200

    @app.route('/webhook', methods=['POST'])
    def stripe_webhook():
        payload = request.get_data(as_text=True)
        sig_header = request.headers.get('Stripe-Signature')

        # Log the payload and signature header for debugging
        print(f"Payload: {payload}")
        print(f"Signature Header: {sig_header}")

        event = None

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except ValueError as e:
            print(f"ValueError: {e}")
            return jsonify(success=False, error=str(e)), 400
        except stripe.error.SignatureVerificationError as e:
            print(f"SignatureVerificationError: {e}")
            return jsonify(success=False, error=str(e)), 400

        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            user_id = session['metadata']['user_id']
            project_id = ObjectId(session['metadata']['project_id'])

            app.db.vitrine.update_one(
                {"project_id": project_id},
                {"$push": {"access_list": user_id}}
            )
            print(f"User {user_id} added to access list of project {project_id}")

        return jsonify(success=True), 200


    #Add Element
    @app.route("/edit_project/<project_id>/add_element", methods=["POST"])
    @requires_auth
    def add_element(project_id):
        user_id = request.user.get('sub')

        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        data = request.json
        section = data.get("section")
        subsection = data.get("subsection")
        element_name = data.get("element_name")

        try:
            result = app.db.projects.update_one(
                {"_id": project_id},
                {"$set": {f"sections.{section}.{subsection}.{element_name}": {"images": [], "steps": []}}}
            )

            if result.modified_count == 0:
                return jsonify({"status": "error", "message": "Project or section or subsection not found"}), 404

            updated_project = app.db.projects.find_one({"_id": project_id})
            updated_project["_id"] = str(updated_project["_id"])

            return jsonify({"status": "success", "message": "Element added successfully", "updated_project": updated_project})
        except Exception as e:
            print("Error:", e)
            return jsonify({"status": "error", "message": "An error occurred"}), 500
        


    #GPT
    @app.route('/edit_project/<project_id>/get-price-estimate', methods=['POST'])
    @requires_auth
    def get_price_estimate(project_id):
        user_id = request.user.get('sub')

        # Проверка подлинности клиента
        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        project = app.db.projects.find_one({"_id": ObjectId(project_id), "user_id": user_id})
        if not project:
            return jsonify({"status": "error", "message": "Project not found"}), 404

        project_description = f"Hi! I would like to get an appraisal of the condition of a 2006 Regal 2665 Commodore boat that is selling for $20,000. Here is the inspection data:"
        project_description = f"information about the vessel: {project['boat_make']}, Boat model: {project['boat_model']}, Year: {project['year']}, Length: {project['length']}, Engine: {project['engine']}, Price: the seller wants for the yacht {project['price']}"

        sections_description = ""
        for section_name, section_content in project['sections'].items():
            for subsection_name, subsection_content in section_content.items():
                for element_name, element_content in subsection_content.items():
                    if element_content['steps']:
                        element_desc = f"Element {element_name} with steps: {element_content['steps']}"
                        sections_description += f"\nSection {section_name}, Subsection {subsection_name}: {element_desc}"

        print(sections_description)

        prompt = f"Hi! I would like to get an estimate of the condition of the boat: {project_description}, Here is the information from the inspection::\n{sections_description}, Based on the information provided, make an optimistic assessment of the boat's condition, describing the problems as easily solvable, and provide an approximate cost of components to fix them."

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an assistant who estimates the value of yachts based on the provided data and descriptions. You need to estimate the approximate value of this yacht. You need to give a neutral answer you need to find similar yachts and their average price the buyer indicates the price he wants for selling this yacht."},
                    {"role": "user", "content": prompt}
                ]
            )
            price_estimate = response.choices[0].message.content.strip()
            print(f'ответ {price_estimate}')
            return jsonify({'price_estimate': price_estimate})
        except Exception as e:
            print(f"An error occurred: {e}")
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        



    @app.route('/api/deleteFinalNote/<project_id>', methods=['POST'])
    @requires_auth
    def delete_final_note(project_id):
        user_id = request.user.get('sub')

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        project = app.db.projects.find_one({"_id": project_id, "user_id": user_id})
        if not project:
            return jsonify({"status": "error", "message": "Project not found"}), 404

        app.db.projects.update_one(
            {"_id": project_id},
            {"$unset": {"final_note": ""}}
        )

        updated_project = app.db.projects.find_one({"_id": project_id})
        updated_project["_id"] = str(updated_project["_id"])

        return jsonify({"status": "success", "message": "Final note deleted successfully", "updated_project": updated_project}), 200


    @app.route('/edit_project/<project_id>/add-final-note', methods=['POST'])
    @requires_auth
    def add_final_note(project_id):
        user_id = request.user.get('sub')

        try:
            project_id = ObjectId(project_id)
        except Exception as e:
            return jsonify({"status": "error", "message": "Invalid project_id"}), 400

        if not check_project_owner(user_id, project_id):
            return jsonify({"status": "error", "message": "Unauthorized access"}), 403

        data = request.get_json()
        final_note = data.get('final_note')

        if not final_note:
            return jsonify({"message": "Final note is required"}), 400

        result = app.db.projects.update_one(
            {"_id": ObjectId(project_id), "user_id": user_id},
            {"$set": {"final_note": final_note}}
        )

        updated_project = app.db.projects.find_one({"_id": project_id})
        updated_project["_id"] = str(updated_project["_id"])

        print(updated_project)

        if result.modified_count == 1:
            return jsonify({"status": "success", "updated_project": updated_project}), 200
        else:
            return jsonify({"message": "Failed to add final note"}), 400

    if __name__ == "__main__":
        app.run(debug=True)
    
    return app
