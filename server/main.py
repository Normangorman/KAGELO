import flask
import json
import codecs
import urllib
import MySQLdb as mariadb
from flask_cors import CORS
from flask import jsonify
import server.secrets as secrets
import server.queries as queries
import server.ratings as ratings
import server.utils as utils
from server.models import *
from server.constants import DEFAULT_RATING

app = flask.Flask(__name__)
CORS(app) # enable cross-origin requests
app.debug = True

db_connection = mariadb.connect(host=secrets.DB_HOST, user=secrets.DB_USER, passwd=secrets.DB_PASS, db=secrets.DB_DB)

def check_ip_whitelisted(req):
    return req.remote_addr in IP_WHITELIST

def run_query(query, params):
    with db_connection.cursor() as cursor:
        cursor.execute(query, params)
    db_connection.commit()

def get_one_row(query, params):
    with db_connection.cursor() as cursor:
        n = cursor.execute(query, params)
        #utils.log("get_one_row", n)
        return cursor.fetchone()

def get_all_rows(query, params):
    with db_connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()

def get_one_row_as_obj(db_object_class, query, params):
    row = get_one_row(query, params)
    #utils.log("get_one_row_as_obj", row)
    if row:
        return db_object_class.from_row(row)

def handle_request_one_row(db_object_class, query, params):
    try:
        obj = get_one_row_as_obj(db_object_class, query, params)
        return jsonify(obj.to_dict())
    except Exception as e:
        utils.log("ERROR couldn't deserialize row: " + str(e))
        return jsonify("null")

def handle_request_all_rows(db_object_class, query, params):
    rows = get_all_rows(query, params)
    try:
        items = [db_object_class.from_row(row).to_dict() for row in rows]
        return jsonify(items)
    except Exception as e:
        utils.log("ERROR couldn't deserialize row: " + str(e))
        return jsonify("null");

def list_routes():
    output = []
    for rule in app.url_map.iter_rules():
        options = {}
        for arg in rule.arguments:
            options[arg] = "[{0}]".format(arg)
        methods = ','.join(rule.methods)
        url = flask.url_for(rule.endpoint, **options)
        line = "{0} {1} {2}".format(rule.endpoint, methods, url)
        output.append(line)

    return sorted(output)

def db_get_player(username):
    return get_one_row_as_obj(Player, queries.get_player, (username, ))

def db_get_player_rating(username, region, kag_class):
    return get_one_row_as_obj(PlayerRating, queries.get_player_rating, (username, region, kag_class))

def db_update_player(player):
    run_query(queries.update_player, (player.username, player.nickname, player.clantag,
                                      player.gender, player.head))

def db_update_player_rating(pr):
    run_query(queries.update_player_rating, (pr.username, pr.region, pr.kag_class, pr.rating,
                                             pr.wins, pr.losses))

def update_ratings(match):
    utils.log("Updating ratings...")
    p1 = db_get_player_rating(match.player1, match.region, match.kag_class)
    p2 = db_get_player_rating(match.player2, match.region, match.kag_class)

    if not p1:
        utils.log("Creating new PlayerRating", (match.player1, match.region, match.kag_class))
        p1 = PlayerRating()
        p1.username = match.player1
        p1.region = match.region
        p1.kag_class = match.kag_class
        p1.set_defaults()
    if not p2:
        utils.log("Creating new PlayerRating", (match.player2, match.region, match.kag_class))
        p2 = PlayerRating()
        p2.username = match.player2
        p2.region = match.region
        p2.kag_class = match.kag_class
        p2.set_defaults()

    p1.validate()
    p2.validate()

    #utils.log("Old p1", p1.serialize())
    #utils.log("Old p2", p2.serialize())

    (p1_new_rating, p2_new_rating) = ratings.get_new_ratings(
            p1.rating, p2.rating, match.player1_score, match.player2_score)
    utils.log("Old ratings {0} {1}".format(p1.rating, p2.rating))
    utils.log("New ratings {0} {1}".format(p1_new_rating, p2_new_rating))
    p1.rating = p1_new_rating
    p2.rating = p2_new_rating

    if match.player1_score > match.player2_score:
        p1.wins += 1
        p2.losses += 1
    else:
        p1.losses += 1
        p2.wins += 1

    #utils.log("New p1", p1.serialize())
    #utils.log("New p2", p2.serialize())
    db_update_player_rating(p1)
    db_update_player_rating(p2)

def update_players(match):
    utils.log("Updating players...")
    p1_username = match.player1
    p2_username = match.player2
    p1 = db_get_player(p1_username)
    p2 = db_get_player(p2_username)

    if not p1:
        utils.log("Creating new player", p1_username)
        p1 = Player()
        p1.username = p1_username
        p1.set_defaults()
    if not p2:
        utils.log("Creating new player", p2_username)
        p2 = Player()
        p2.username = p2_username
        p2.set_defaults()

    db_update_player(p1)
    db_update_player(p2)

def insert_match(match):
    utils.log("Inserting match...")
    params = (match.region, match.player1, match.player2, match.kag_class, match.match_time,
              match.player1_score, match.player2_score, match.duel_to_score)
    run_query(queries.create_match_history, params)

def process_match(match):
    utils.log("Processing match " + match.serialize())
    update_players(match)
    insert_match(match)
    update_ratings(match)

@app.route('/players/<username>')
def get_player(username):
    return handle_request_one_row(Player, queries.get_player, (username, ))

@app.route('/match_history/<region>/<match_time>')
def get_match_history(region, match_time):
    return handle_request_one_row(MatchHistory, queries.get_match_history, (region, match_time))

@app.route('/player_ratings/<username>/<region>')
def get_player_ratings(username, region):
    rows = get_all_rows(queries.get_player_ratings, (username, region))
    data = {"username": username, "region": region}

    for kag_class in VALID_KAG_CLASSES:
        data[kag_class] = {"rating": DEFAULT_RATING, "wins": 0, "losses": 0}

    for row in rows:
        try:
            pr = PlayerRating.from_row(row)
        except Exception as e:
            utils.print("ERROR couldn't deserialize row: " + e.message)
            return "null"

        data[pr.kag_class] = {"rating": pr.rating, "wins": pr.wins, "losses": pr.losses}
    
    return jsonify(data)

@app.route('/player_match_history/<username>')
def get_match_history_for_player(username):
    return handle_request_all_rows(MatchHistory, queries.get_player_match_history, (username, username))

@app.route('/recent_match_history')
@app.route('/recent_match_history/<limit>')
def get_recent_matches(limit=20):
    if type(limit) == str:
        try:
            limit = int(limit)
        except ValueError:
            limit = 20
    return handle_request_all_rows(MatchHistory, queries.get_recent_match_history, (limit,))

@app.route('/leaderboard/<region>/<kag_class>')
def get_leaderboard(region, kag_class):
    if region_validator(region) and kag_class_validator(kag_class):
        return handle_request_all_rows(LeaderboardRow, queries.get_leaderboard, (region, kag_class))
    else:
        flask.abort(400)

@app.route('/create_match', methods=['POST'])
def create_match():
    if not check_ip_whitelisted(flask.request):
        flask.abort(403)

    data = None
    if flask.request.form:
        data = flask.request.form
    elif flask.request.args:
        data = flask.request.args
    else:
        utils.log("No data supplied")
        flask.abort(400)

    #utils.log("Request data", data)
    #utils.log("Request data.match_time", data["match_time"])
    try:
        match = MatchHistory.from_dict(data)
    except Exception as e:
        utils.log("ERROR couldn't deserialize match: " + str(e))
        flask.abort(400)

    if match.validate():
        utils.log("Valid match.")
        process_match(match)
        return jsonify("true")
    else:
        utils.log("Invalid match")
        flask.abort(400)

@app.route('/')
def get_homepage():
    output = "<html><body><h1>KAGELO API</h1>"
    output += "<ul>"
    for route in list_routes():
        output += "<li>" + str(route) + "</li>"
    output += "</ul>"
    output += "</body></html>"
    output = output.replace("%5B", "{")
    output = output.replace("%5D", "}")
    return output

@app.after_request
def add_header(response):
    response.cache_control.max_age = 60
    return response
