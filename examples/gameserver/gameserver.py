from math import asin, cos, radians, sin, sqrt

from datadivr import BackgroundTasks, app
from datadivr.handlers.registry import HandlerType, websocket_handler
from datadivr.transport.messages import create_message, send_message
from datadivr.transport.models import WebSocketMessage
from datadivr.transport.server import clients, get_client_state, update_client_state
from datadivr.utils.logging import get_logger, setup_logging
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import hashlib
import hmac
import html
import json
import secrets
import shutil
import string
import time
from fastapi import File, Form, UploadFile, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi import BackgroundTasks as FABackgroundTask
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr, BaseModel

# Initialize logging first, before getting the logger
setup_logging()
logger = get_logger(__name__)



import os


from dotenv import load_dotenv
load_dotenv()

global taskdata
taskdata = {"tasks":[]}
serverURL = ""
serverWS = ""
localserver = True

storage_path = os.getenv("PERSISTANT_PATH", "examples/gameserver/")

### ADMIN
# No default: if ADMIN_TOKEN is not set, the admin endpoints are disabled.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
if not ADMIN_TOKEN:
    logger.warning("ADMIN_TOKEN is not set - admin endpoints are disabled")

# Secret used to sign login session cookies. If unset, a random one is
# generated per process, which logs everyone out on restart.
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
SESSION_COOKIE = "cb_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

userskin_path = ""
tasks_path = ""
tracks_path = ""

if storage_path != "examples/gameserver/":
    localserver = False
print("we use:", storage_path)

if localserver:
    userskin_path = "userskins"
else:
    userskin_path = os.path.join(storage_path, "userskins")

tasks_path =  os.path.join(storage_path,  'tasks') 
tracks_path = os.path.join(storage_path,  'tracks') 

# debug open /storage, list all files, print
persistantFiles = os.listdir(storage_path)
print(persistantFiles)
if "users.json" not in persistantFiles:
    print("not found")
    with open(os.path.join(storage_path, 'users.json'), 'w') as f:
        data = {"users":[]}
        json.dump(data, f)

if os.path.isdir(userskin_path):
    print(os.listdir(userskin_path))
else:
    print("Skins Doesn't exists")
    os.mkdir(userskin_path)


    #os.mkdir(tasks_path)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
source_tasks = os.path.join(BASE_DIR, "tasks")
if not os.path.exists(tasks_path) or not os.listdir(tasks_path):
    print("tasks missing or empty → copying files")
    os.makedirs(tasks_path, exist_ok=True)
    shutil.copytree(source_tasks, tasks_path, dirs_exist_ok=True)
    print("after copy:", os.listdir(tasks_path))
else:
    print("tasks already exist:", os.listdir(tasks_path))

print("SOURCE:", source_tasks)
print("SOURCE EXISTS:", os.path.exists(source_tasks))
print("DEST:", tasks_path)


if os.path.isdir(tracks_path):
    print(os.listdir(tracks_path))
else:
    print("tasks Doesn't exists")
    os.mkdir(tracks_path)

print("Serving userskins from:", userskin_path)
print("Absolute path:", os.path.abspath(userskin_path))
print("Files:", os.listdir(userskin_path))


if localserver:
    serverURL = "http://127.0.0.1:8765"
    serverWS = "ws://localhost:8765/ws"
else:
    serverURL = "https://cloudbase.lab.lbi-netmed.com"
    serverWS = "wss://cloudbase.lab.lbi-netmed.com/ws"

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/userskins", StaticFiles(directory=userskin_path), name="userskins")
templates = Jinja2Templates(directory="templates")

#task_dir = os.path.join(os.path.dirname(__file__),  'tasks')
taskfiles = os.listdir(tasks_path)

'''
for t in taskfiles:
    with open(tasks_path +'/' + t, 'r', encoding='utf-8') as f:
        #global userdb 
        thistask = json.load(f)
        if "track" not in thistask:
            thistask["track"] = 'none'
        if "tracks" not in thistask:
            thistask["tracks"] = []
        #print(thistask)

        taskdata["tasks"].append(thistask)
        f.close()
'''
def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(secrets.choice(chars) for _ in range(size))


### USERS / PASSWORDS
USERS_FILE = os.path.join(storage_path, "users.json")
PBKDF2_ITERATIONS = 200_000
HASH_PREFIX = "pbkdf2_sha256"


def hash_password(pw) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(pw).encode("utf-8"), salt.encode("ascii"), PBKDF2_ITERATIONS)
    return f"{HASH_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def is_hashed(stored) -> bool:
    return isinstance(stored, str) and stored.startswith(HASH_PREFIX + "$")


def verify_password(pw, stored) -> bool:
    if pw is None or stored is None:
        return False
    if not is_hashed(stored):
        # legacy plaintext entry (migrated at startup, kept as a fallback)
        return hmac.compare_digest(str(pw), str(stored))
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", str(pw).encode("utf-8"), salt.encode("ascii"), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


def load_userdb(strict: bool = False):
    """strict=True raises instead of returning an empty DB; use it before writing,
    so a read error can never overwrite users.json with an empty list."""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("users"), list):
            return data
        raise ValueError("users.json has no 'users' list")
    except (OSError, ValueError):
        if strict:
            raise
        logger.exception("Could not read users.json")
    return {"users": []}


def save_userdb(data) -> None:
    # write to a temp file and swap, so a crash never leaves a half-written users.json
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, USERS_FILE)


def migrate_plaintext_passwords() -> None:
    try:
        data = load_userdb(strict=True)
    except (OSError, ValueError):
        logger.exception("Skipping password migration: users.json unreadable")
        return
    changed = 0
    for user in data["users"]:
        if "pw" in user and not is_hashed(user["pw"]):
            user["pw"] = hash_password(user["pw"])
            changed += 1
    if changed:
        save_userdb(data)
        logger.info("Hashed plaintext passwords in users.json", count=changed)


migrate_plaintext_passwords()


def public_user(user: dict) -> dict:
    """User fields that are safe to send to the browser (no password / email)."""
    return {k: v for k, v in user.items() if k not in ("pw", "email")}


def searchUser(name, pw):
    userdb = load_userdb()
    for user in userdb["users"]:
        if user.get("name") == name and verify_password(pw, user.get("pw")):
            return user
    return None


### SESSIONS (signed cookie: name|expiry|signature)
def make_session(name: str) -> str:
    expires = str(int(time.time()) + SESSION_MAX_AGE)
    payload = f"{name}|{expires}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def read_session(token) -> str | None:
    if not token:
        return None
    try:
        name, expires, sig = token.rsplit("|", 2)
    except ValueError:
        return None
    payload = f"{name}|{expires}"
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if not expires.isdigit() or int(expires) < time.time():
        return None
    return name


def set_session_cookie(response: Response, name: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        make_session(name),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=not localserver,
    )


### ADMIN AUTH / FILE NAME SAFETY
def require_admin(token: str) -> None:
    if not ADMIN_TOKEN or not hmac.compare_digest(str(token), ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


SKIN_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_SKIN_BYTES = 10 * 1024 * 1024


def safe_name_part(value) -> str:
    """Make one piece of a track file name safe (no path separators or '..')."""
    return "".join(c if c.isalnum() or c in "-. " else "-" for c in str(value)).strip(". ")


def safe_filename(name) -> str:
    """Reduce a client-supplied file name to a bare name inside the target folder."""
    base = os.path.basename(str(name or "").replace("\\", "/"))
    if base in ("", ".", "..") or base.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid file name")
    return base

def getUser(name):
    userdb = load_userdb()
    for user in userdb["users"]:
        if user["name"] == name:
            return user
    return None


def reload_tasks():
    taskdata["tasks"] = []
    
    for t in os.listdir(tasks_path):
        with open(os.path.join(tasks_path, t), 'r', encoding='utf-8') as f:
            thistask = json.load(f)

            if "track" not in thistask:
                thistask["track"] = 'none'
            if "tracks" not in thistask:
                thistask["tracks"] = []

            taskdata["tasks"].append(thistask)
     

# example messages
# {"event_name": "GAMESERVER_SET_NAME", "to": "others", "payload": {"name": "CLI" } }
# {"event_name": "GAMESERVER_INFO_UPDATE", "to": "others", "payload": {"latitude": 48.23747967660676, "longitude": 16.416320800781254, "altitude": 500, "direction": 90}}


def is_within_range(lat1: float, lon1: float, lat2: float, lon2: float, max_range_km: float = 100.0) -> bool:
    """
    Determine if two geographical points are within a specified range.

    This function calculates the great-circle distance between two points
    on the Earth's surface given their latitude and longitude in degrees.
    It returns True if the distance is less than or equal to the specified
    maximum range in kilometers.

    Parameters:
    - lat1 (float): Latitude of the first point in degrees.
    - lon1 (float): Longitude of the first point in degrees.
    - lat2 (float): Latitude of the second point in degrees.
    - lon2 (float): Longitude of the second point in degrees.
    - max_range_km (float): Maximum range in kilometers. Default is 10.0 km.

    Returns:
    - bool: True if the distance between the two points is within the specified range, False otherwise.
    """
    lat1, lon1 = radians(lat1), radians(lon1)
    lat2, lon2 = radians(lat2), radians(lon2)
    R = 6371.0
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    distance = R * c
    return distance <= max_range_km

print(f"Current Working Directory: {os.getcwd()}")
print(f"Does .env exist here? {os.path.exists('.env')}")
if not os.getenv("MAIL_PASSWORD"):
    logger.warning("MAIL_PASSWORD is not set - password reset emails will fail")

conf = ConnectionConfig(
    MAIL_USERNAME = "sepppCloudbase@gmail.com",
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD"),
    MAIL_FROM = "noreply@cloudbase.com",
    MAIL_PORT = 587,
    MAIL_SERVER = "smtp.gmail.com",
    MAIL_STARTTLS = True,
    MAIL_SSL_TLS = False,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True
)

class EmailSchema(BaseModel):
    email: EmailStr
    

@app.post("/send-password")
async def send_password_email(request: Request, user: EmailSchema, background_tasks: FABackgroundTask):
    # Passwords are stored hashed, so we can't send the old one: if name and
    # email match, set a new random password and email that instead.
    thisuser = await request.json()
    name = thisuser.get("name")

    try:
        users = load_userdb(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="User database error")
    match = None
    for u in users["users"]:
        if u.get("name") == name and u.get("email") and str(u["email"]).lower() == str(user.email).lower():
            match = u
            break

    if match is not None:
        new_password = id_generator()
        body = f"""
        <p>Hi {html.escape(str(name))},</p>
        <p>Your password has been reset. Your new password is: <strong>{new_password}</strong></p>
        """
        message = MessageSchema(
            subject="Your New Password",
            recipients=[user.email],
            body=body,
            subtype=MessageType.html
        )
        # send first and only store the new password once the mail went out,
        # otherwise a mail failure would lock the user out
        try:
            await FastMail(conf).send_message(message)
        except Exception:
            logger.exception("Password reset email failed", name=name)
            return {"message": "Could not send the email, please try again later"}
        match["pw"] = hash_password(new_password)
        save_userdb(users)

    # same answer either way, so this can't be used to probe names/emails
    return {"message": "If the name and email match an account, an email with a new password has been sent"}


@app.get("/forgot")
async def newaccount(request: Request):
    return templates.TemplateResponse("resetPW.html", {"request": request,  "json_data":  {"tasks":taskfiles, "serverURL":serverURL}})












@app.get("/admin/download_users")
async def download_users(token: str = ""):
    require_admin(token)

    file_path = USERS_FILE

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="users.json not found")

    return FileResponse(
        path=file_path,
        filename="users.json",
        media_type="application/json"
    )

@app.post("/pw")
async def check_pw(request: Request, response: Response):
    userdb = load_userdb()

    thisuser = await request.json()
    name = thisuser.get("name")
    pw = thisuser.get("pw")

    print("LOGIN REQUEST:", name)

    for user in userdb["users"]:
        if user.get("name") == name:
            if verify_password(pw, user.get("pw")):
                # log in via a signed HttpOnly cookie instead of putting the password in the URL
                set_session_cookie(response, name)
                return {"message": "CORRECT", "data": {"name": name}}
            else:
                return {"message": "WRONG PW"}

    return {"message": f"NO USER CALLED {name}"}


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, token: str = ""):
    require_admin(token)

    files = os.listdir(tasks_path)
    # token already matched ADMIN_TOKEN, but escape it anyway before putting it in HTML/JS
    token_attr = html.escape(token, quote=True)
    token_js = json.dumps(token).replace("<", "\\u003c")

    page = f"""
    <html>
    <head>
        <title>Admin Panel</title>
        <style>
            body {{ font-family: Arial; padding: 20px; }}
            .task {{ margin-bottom: 10px; }}
            button {{ margin-left: 10px; }}
        </style>
    </head>
    <body>
        <h1>Admin Panel</h1>
        <h2>User Data</h2>

        <button onclick="downloadUsers()">Download users.json</button>
        <h2>Upload Task</h2>
        <form action="/admin/upload_task?token={token_attr}" method="post" enctype="multipart/form-data">
            <input type="file" name="file" accept=".json" required>
            <button type="submit">Upload</button>
        </form>

        <h2>Existing Tasks</h2>
    """

    for f in files:
        page += f"""
        <div class="task">
            {html.escape(f)}
            <form style="display:inline;" action="/admin/delete_task?token={token_attr}" method="post">
                <input type="hidden" name="filename" value="{html.escape(f, quote=True)}">
                <button type="submit">Delete</button>
            </form>
        </div>
        """

    page += f"""
    </body>
    <script>
        const TOKEN = {token_js};

        function downloadUsers() {{
            const url = `/admin/download_users?token=${{encodeURIComponent(TOKEN)}}`;

            const a = document.createElement("a");
            a.href = url;
            a.download = "users.json";
            document.body.appendChild(a);
            a.click();
            a.remove();
        }}
    </script>
    </html>
    """

    return HTMLResponse(content=page)
@app.post("/admin/delete_task")
async def delete_task(filename: str = Form(...), token: str = ""):
    require_admin(token)

    filename = safe_filename(filename)
    file_path = os.path.join(tasks_path, filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    os.remove(file_path)
    reload_tasks()
    return {"message": f"{filename} deleted"}



@app.post("/admin/upload_task")
async def upload_task(file: UploadFile = File(...), token: str = ""):
    require_admin(token)

    filename = safe_filename(file.filename)
    if not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files allowed")

    file_path = os.path.join(tasks_path, filename)

    try:
        content = await file.read()

        # validate JSON
        json.loads(content)

        with open(file_path, "wb") as f:
            f.write(content)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    reload_tasks()
    return {"message": f"{filename} uploaded"}
@app.post("/upload")
async def upload(
    response: Response,
    file: UploadFile = File(...),
    myjson: str = Form(...)
):
    try:
        userdb = load_userdb(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="User database error")

    thisuser = json.loads(myjson)
    username = thisuser.get("name")

    if not isinstance(username, str) or not username.strip():
        raise HTTPException(status_code=400, detail="Missing username")

    print("NEW USER REQUEST:", username)

    if any(u.get("name") == username for u in userdb["users"]):
        return {"message": "user exists"}

    # save the uploaded skin; never overwrite someone else's file
    skin_name = safe_filename(file.filename)
    if os.path.splitext(skin_name)[1].lower() not in SKIN_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Skin must be a .png or .jpg image")
    content = await file.read(MAX_SKIN_BYTES + 1)
    if len(content) > MAX_SKIN_BYTES:
        raise HTTPException(status_code=400, detail="Skin file is too large")
    os.makedirs(userskin_path, exist_ok=True)
    if os.path.exists(os.path.join(userskin_path, skin_name)):
        skin_name = f"{id_generator()}_{skin_name}"
    try:
        with open(os.path.join(userskin_path, skin_name), "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

    # create the user; only the hash of the generated password is stored
    password = id_generator()
    thisuser["pw"] = hash_password(password)
    thisuser["tex"] = skin_name
    userdb["users"].append(thisuser)

    try:
        save_userdb(userdb)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save user: {str(e)}")

    return {
        "message": f"Welcome {username}! your Password is {password}"
    }

# HTML ROUTE
@app.get("/createAccount")
async def newaccount(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request, "json_data":  {"tasks":taskfiles, "serverURL":serverURL}})

@app.get("/clients")
async def showclients():
    #print("clients:", clients)
    return json.dumps(clients)

@app.get("/cloudbase1337", response_class=HTMLResponse)
async def multiplayermap(request: Request):
    taskfiles = os.listdir(tasks_path)
    name = read_session(request.cookies.get(SESSION_COOKIE))
    thisuser = getUser(name) if name else None
    if thisuser is None:
        return templates.TemplateResponse("login.html", {"request": request, "json_data":  {"tasks":taskfiles, "serverURL":serverURL}})
    return templates.TemplateResponse("client.html", {"request": request, "json_data": {"tasks":taskfiles, "user":public_user(thisuser), "livetask":5, "serverURL":serverURL, "serverWS":serverWS}})


@app.get("/cloudbase1337/{name}/{pw}", response_class=HTMLResponse)
async def multiplayermap_legacy(request: Request, name: str, pw: str):
    """Old link format with the password in the URL. Kept so existing links/clients
    still work: log in, set the session cookie and redirect to the clean URL."""
    if searchUser(name, pw) is None:
        return RedirectResponse(url=f"{serverURL}/cloudbase1337", status_code=303)
    redirect = RedirectResponse(url=f"{serverURL}/cloudbase1337", status_code=303)
    set_session_cookie(redirect, name)
    return redirect


@websocket_handler("GAMESERVER_CLIENT_UPDATE_STATE", HandlerType.SERVER)
async def info_update_handler(message: WebSocketMessage) -> None:
    """
    Handle position updates from clients.

    This handler processes incoming WebSocket messages containing
    geographical data from clients. It updates the client's position
    information in the server's client registry.

    Example message format:
    {
        "event_name": "GAMESERVER_CLIENT_UPDATE",
        "to": "others",
        "payload": {
            "lat: 48.210033,
            "long": 16.363449,
            "alt": 2345,
            "rot_x": 0.3,
            "rot_y": 0.4,
            "rot_z": 0.5,
            "type": 1,
            "anim": 2
        }
    }

    Parameters:
    - message (WebSocketMessage): The incoming WebSocket message containing
      the client's position data.
    """
    try:
        data = message.payload
        print("info_update_handler payload:", message.payload)
        Name = data.get("name")
        latitude = data.get("lat")
        longitude = data.get("long")
        altitude = data.get("alt")
        rotation_x = data.get("rot_x")
        rotation_y = data.get("rot_y")
        rotation_z = data.get("rot_z")
        aircraft_type = data.get("type")
        animation_state = data.get("anim")
        Tex = data.get("tex")
        Tp = data.get("tp")
        Flag = data.get("flag")
        '''
        if not all(
            isinstance(x, int | float | any)
            for x in [name, latitude, longitude, altitude, rotation_x, rotation_y, rotation_z, aircraft_type, animation_state]
        ):
            for x in [
                name,
                latitude,
                longitude,
                altitude,
                rotation_x,
                rotation_y,
                rotation_z,
                aircraft_type,
                animation_state,
            ]:
                print(x, type(x))

            logger.error("Invalid data types in payload")
            return
        '''
        # Retrieve the current name or use a default if not set
        state = get_client_state(message.from_id)
        current_name = state.get("name", "Unknown") if state else "Unknown"

        # Update client state
        update_client_state(
            message.from_id,
            name=Name,
            lat=latitude,
            long=longitude,
            alt=altitude,
            rot_x=rotation_x,
            rot_y=rotation_y,
            rot_z=rotation_z,
            type=aircraft_type,
            anim=animation_state,
            tp = Tp,
            flag = Flag,
            tex=Tex,
        )
        logger.debug("Updated client info", client_id=message.from_id, data=data)
    except Exception as e:
        logger.exception("Error handling GAMESERVER_CLIENT_UPDATE", error=str(e))


@BackgroundTasks.periodic(interval=1, name="GAMESERVER_broadcast_nearby_clients")
async def broadcast_updates() -> None:
    """
    Periodically broadcast updates about nearby clients to each connected client.

    This function runs every second and performs the following steps for each client:
    1. Gets the client's current position
    2. Finds all other clients within the specified range
    3. Sends a GAMESERVER_NEARBY_UPDATE message containing information about nearby clients

    The message format sent to each client is:
    {
        "event_name": "GAMESERVER_NEARBY_UPDATE",
        "payload": {
            "nearby_clients": [
                {
                    "client_id": "uuid",
                    "name": "Client Name",
                    "lat": float,
                    "long": float,
                    "alt": float,
                    "rot_x": float,
                    "rot_y": float,
                    "rot_z": float,
                    "type": int,
                    "anim": int
                },
                ...
            ]
        }
    }
    """
    logger.debug("Starting broadcast cycle")

    # Iterate through all connected clients
    for client_id, client_data in clients.items():
        state = client_data["state"]

        # Get current client's position
        lat1, lon1 = state.get("lat", 0), state.get("long", 0)

        # Skip clients without valid position data
        if lat1 == 0 and lon1 == 0:
            continue

        nearby_clients = []

        # Check distance to all other clients
        for other_id, other_data in clients.items():
            # Skip self
            if client_id == other_id:
                continue

            other_state = other_data["state"]
            lat2, lon2 = other_state.get("lat", 0), other_state.get("long", 0)
            # Skip clients without valid position data
            if lat2 == 0 and lon2 == 0:
                continue

            # If client is within range, add their info to the nearby list
            if is_within_range(lat1, lon1, lat2, lon2):
                nearby_clients.append({
                    "client_id": other_id,
                    "name": other_state.get("name"),
                    "lat": lat2,
                    "long": lon2,
                    "alt": other_state.get("alt"),
                    "rot_x": other_state.get("rot_x"),
                    "rot_y": other_state.get("rot_y"),
                    "rot_z": other_state.get("rot_z"),
                    "type": other_state.get("type"),
                    "anim": other_state.get("anim"),
                    "tp" :  other_state.get("tp"),
                    "flag":  other_state.get("flag"),
                    "tex":  other_state.get("tex"),
                })

        # also send if no nearby clients, to potentially clean old clients, could be improved:
        # TODO: check if last update was already empty for this client, if so, skip

        # if nearby_clients: # only send if there are nearby clients

        message = create_message(
            event_name="GAMESERVER_NEARBY_UPDATE", payload={"nearby_clients": nearby_clients}, to=client_id
        )
        await send_message(client_data["websocket"], message)



@websocket_handler("GAMESERVER_CLIENT_GPSTRACK", HandlerType.SERVER)
async def gpstrack_handler(message: WebSocketMessage) -> None:
    
    # sanitise each piece so the file stays inside tracks/ and get_task can still split on "_"
    parts = [safe_name_part(message.payload["taskname"]), safe_name_part(message.payload["name"]),
             safe_name_part(message.from_id[:5]), safe_name_part(message.payload["rtime"])]
    if not all(parts):
        logger.error("Invalid GPS track file name", parts=parts)
        return
    filename = "_".join(parts)
    print(filename)

    with open(os.path.join(tracks_path, filename + '.json'), 'w', encoding='utf-8') as f:
        json.dump(message.payload,f)

    #print(message.payload)
    

@websocket_handler("GAMESERVER_CLIENT_SETNAME", HandlerType.SERVER)
async def set_name_handler(message: WebSocketMessage) -> None:
    """
    Handle the GAMESERVER_CLIENT_SETNAME event from clients.

    This handler allows clients to update their display name on the server.
    It processes incoming WebSocket messages containing the new name and
    updates the client's information in the server's client registry.

    Example message format:
    {
        "event_name": "GAMESERVER_CLIENT_SETNAME",
        "to": "others",
        "payload": {
            "name": "Timmey"
        }
    }

    Parameters:
    - message (WebSocketMessage): The incoming WebSocket message containing
      the client's new name.
    """

    try:
        print("set_name_handler payload:", message.payload)
        name = message.payload.get("name", "")
        tex = message.payload.get("tex", "")
        if not isinstance(name, str) or not name.strip():
            logger.error("Invalid name format")
            return

        # Get existing state to preserve other fields
        existing_state = get_client_state(message.from_id) or {}

        # Create new state dict with updated name
        new_state = existing_state.copy()
        new_state["name"] = name.strip()
        new_state["tex"] = tex.strip()

        # Update state with all fields
        update_client_state(message.from_id, **new_state)
        logger.debug("Updated client name", client_id=message.from_id, name=name)



    except Exception as e:
        logger.exception("Error handling GAMESERVER_CLIENT_SETNAME", error=str(e))


'''
@websocket_handler("GAMESERVER_CLIENT_GETTASKLIST", HandlerType.SERVER)
async def set_tasklist_handler(message: WebSocketMessage) -> None:
    import os
    
    filepath = os.path.dirname(os.path.realpath(__file__))
    #parent = os.path.abspath(os.path.join(filepath, os.pardir))
    taskfiles = os.listdir(filepath + "/tasks")

    try:
        return WebSocketMessage(event_name="TASKLIST", payload={"tasks":taskfiles}, to=message.from_id)
    
    except Exception as e:
        logger.exception("Error handling GAMESERVER_CLIENT_SETNAME", error=str(e))
'''

@websocket_handler("get_task", HandlerType.SERVER)
async def set_task_handler(message: WebSocketMessage) -> None:
    try:
        reload_tasks()
        thistask = {}
        found = False
        for t in taskdata["tasks"]:
            if message.payload.get("name", "") == t["name"]:
                thistask = t
                found = True
                break
        if found:
            trackfiles = os.listdir(tracks_path)

            tname = thistask["name"]
            matchingtracks = []
            for tr in trackfiles:
                name = tr.split("_")
                if name[0] in (tname, safe_name_part(tname)):
                    with open(tracks_path +'/' + tr, 'r', encoding='utf-8') as f: 
                        thistr = json.load(f)
                        matchingtracks.append(thistr)
                    f.close()
                    break

            for t in matchingtracks:
                thisu = getUser(t["name"])
                tex = ""
                flag = "https://flagcdn.com/de.svg"
                if thisu == None:
                    tex = "1.png"
                else:
                    tex = thisu["tex"]
                    flag = thisu["flag"]
                t["tex"] = tex
                t["flag"] = flag


            
            sortedtracks = sorted(matchingtracks, key=lambda k: k.get('rtime', 0), reverse=False)

            thistask["tracks"] = sortedtracks

            return WebSocketMessage(event_name="TASK", payload=thistask, to=message.from_id)
        else:
            print("couldent find task")
    except Exception as e:
        logger.exception("Error handling GAMESERVER_CLIENT_SETNAME", error=str(e))



if __name__ == "__main__":
    import uvicorn
    #global userdb

    #reload_tasks()


    # check if /storage/users.json exist, if not create with default


    if localserver:
        uvicorn.run(app, host="127.0.0.1", port=8765)
    else:
        uvicorn.run(app, host="0.0.0.0", port=8765)
    print("post start")
