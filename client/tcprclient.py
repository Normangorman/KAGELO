import socket
import sys
import re
import traceback
import xmltodict
import time
from enum import Enum

import tcprhandlers
from secrets import RCON_PASSWORD

REQ_UNUSED = 0
REQ_SENT = 1
REQ_ANSWERED = 2
SERVER_IP = "localhost"
SERVER_PORT = 50301
OPEN_REQUESTS = []
REQUEST_HANDLERS = [("ping", tcprhandlers.handle_ping_request)]

class TCPRRequest:
    def __init__(self, reqID, method, params):
        self.reqID = reqID
        self.method = method
        self.params = params
        self.isAnswered = False
        self.answer = ""

    @staticmethod
    def deserialize(xml):
        try:
            xml_dict = xmltodict.parse(xml)
            assert("request" in xml_dict)
            assert("id" in xml_dict["request"])
            assert("method" in xml_dict["request"])
            assert("params" in xml_dict["request"])
        except Exception as e:
            print("Could not deserialize TCPRRequest")
            print(str(e))
            print(traceback.format_exc())
            return None

        reqID = xml_dict["request"]["id"]
        method = xml_dict["request"]["method"]
        params = xml_dict["request"]["params"]
        return TCPRRequest(reqID, method, params)

def authenticate(sock):
    sock.send((RCON_PASSWORD + "\n").encode())

def send_request_response(sock, reqID, response):
    # There shouldn't be "'" symbols in the response because this interferes with the escaping.
    # Just replace them with underscores.
    response = response.replace("'", "_")
    print("    * Sending response: " + response)
    """
    code = "getRules().set_string('TCPR_RES{0}', '{1}'); getRules().set_u8('TCPR_REQ{0}', {2});".format(
            reqID, response, REQ_ANSWERED)
    """
    code = "getRules().set_string('TCPR_RES{0}', '{1}');".format(reqID, response);
    sock.send((code + "\n").encode())

def match_request(line):
    return re.match("^\[\d\d:\d\d:\d\d\]\s(<request>.*</request>)", line)

def add_handler(method, func):
    REQUEST_HANDLERS.push(method, func)

def handle_request(sock, req):
    # Look for appropriate handler
    for method, func in REQUEST_HANDLERS:
        if method == req.method:
            response = func(req)
            send_request_response(sock, req.reqID, response)
            return
    print("No handler available for this request: {}".format(req.method)) 

def handle_line(sock, line):
    match = match_request(line)
    if match:
        print("    * Request detected.")
        request_xml = match.group(1)
        req = TCPRRequest.deserialize(request_xml)
        handle_request(sock, req)

def connect_to_kag():
    with socket.socket() as sock:
        try:
            sock.connect((SERVER_IP, SERVER_PORT))
        except ConnectionError:
            print("Couldn't connect to KAG at {0}:{1}. Is the server running?".format(SERVER_IP, SERVER_PORT))
        print("Connected.")

        authenticate(sock)
        print("Authenticated.")
        print("Listening...")
        for line in sock.makefile('r'):
            print("  RECEIVED: {}".format(line.strip()))
            handle_line(sock, line)
            sys.stdout.flush()

if __name__ == "__main__":
    while True:
        try:
            connect_to_kag()
        except Exception as e:
            print("ERROR: Uncaught exception! Connecting again...")
            print(e)
            time.sleep(1)
