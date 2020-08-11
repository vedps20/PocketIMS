import requests
from bs4 import BeautifulSoup
import json

from .exceptions import IncorrectCredentialsError, UIMSInternalError

BASE_URL = "https://uims.cuchd.in"
AUTHENTICATE_URL = BASE_URL + "/uims/"

ENDPOINTS = {
    "Attendance": "frmStudentCourseWiseAttendanceSummary.aspx",
    "timetable": "frmMyTimeTable.aspx"
}
ERROR_HEAD = 'Whoops, Something broke!'
headers = {'Content-Type': 'application/json'}

class SessionUIMS:
    def __init__(self, uid, password):
        self._uid = uid
        self._password = password
        self.cookies = None
        self.refresh_session()

        self._attendance = None
        self._reportId = None
        self._sessionId = None

    def _login(self):
        response = requests.get(AUTHENTICATE_URL)
        soup = BeautifulSoup(response.text, "html.parser")
        viewstate_tag = soup.find("input", {"name":"__VIEWSTATE"})

        data = {"__VIEWSTATE": viewstate_tag["value"],
                "txtUserId": self._uid,
                "btnNext": "NEXT"}

        response = requests.post(AUTHENTICATE_URL,
                                 data=data,
                                 cookies=response.cookies,
                                 allow_redirects=False)

        soup = BeautifulSoup(response.text, "html.parser")

        password_url = BASE_URL + response.headers["location"]
        response = requests.get(password_url, cookies=response.cookies)
        login_cookies = response.cookies
        soup = BeautifulSoup(response.text, "html.parser")
        viewstate_tag = soup.find("input", {"name":"__VIEWSTATE"})

        data = {"__VIEWSTATE": viewstate_tag["value"],
                "txtLoginPassword": self._password,
                "btnLogin": "LOGIN"}

        response = requests.post(password_url,
                                 data=data,
                                 cookies=response.cookies,
                                 allow_redirects=False)

        incorrect_credentials = response.status_code == 200
        if incorrect_credentials:
            raise IncorrectCredentialsError("Make sure UID and Password are correct.")

        aspnet_session_cookies = response.cookies

        login_and_aspnet_session_cookies = requests.cookies.merge_cookies(login_cookies, aspnet_session_cookies)
        return login_and_aspnet_session_cookies

    def refresh_session(self):
        self.cookies = self._login()

    @property
    def attendance(self):
        if self._attendance is None:
            self._attendance = self._get_attendance()

        return self._attendance

    @property
    def full_attendance(self):
        # getting minimal attendance
        attendance = self.attendance
        # Full report URL
        full_report_url = AUTHENTICATE_URL + ENDPOINTS['Attendance'] + '/GetFullReport'
        # Querying for every subject in attendance
        for subect in attendance:
            data = "{course:'" + subect['EncryptCode']  + "',UID:'" + self._reportId + "',fromDate: '',toDate:''" + ",type:'All'" + ",Session:'" + self._sessionId + "'}"
            response = requests.post(full_report_url, headers=headers, data=data)
            # removing esc sequence chars
            subect['FullAttendanceReport'] = json.loads(json.loads(response.text)['d'])
        return attendance

    @property
    def timetable(self):
        timetable_url = AUTHENTICATE_URL + ENDPOINTS['timetable']
        response = requests.get(timetable_url, cookies=self.cookies)
        soup = BeautifulSoup(response.text, "html.parser")

        viewstate_tag = soup.find("input", {"name":"__VIEWSTATE"})
        viewstate_gen_tag = soup.find("input", {'name': '__VIEWSTATEGENERATOR'})
        event_validation_tag = soup.find("input", {'name': '__EVENTVALIDATION'})
        ctrl_object = soup.find("input", {'name': 'ctl00$ContentPlaceHolder1$ReportViewer1$ctl09$ReportControl$ctl04'})
        hidden_async_cancel = soup.find("input", {'name': 'ctl00$ContentPlaceHolder1$ReportViewer1$AsyncWait$HiddenCancelField'})
        report_viewer_toggle = soup.find("input", {"name": 'ctl00$ContentPlaceHolder1$ReportViewer1$ToggleParam$collapse'})
        report_viewer_collapse = soup.find("input", {"name": 'ctl00$ContentPlaceHolder1$ReportViewer1$ctl07$collapse'})

        data = {
            "__VIEWSTATE": viewstate_tag["value"],
            "__VIEWSTATEGENERATOR": viewstate_gen_tag["value"],
            "__EVENTVALIDATION": event_validation_tag["value"],
            '__ASYNCPOST': 'true',
            # "ctl00$ContentPlaceHolder1$ReportViewer1$ctl09$ReportControl$ctl04": ctrl_object["value"],
            # 'ctl00$ContentPlaceHolder1$ReportViewer1$AsyncWait$HiddenCancelField' : hidden_async_cancel['value'],
            # 'ctl00$ContentPlaceHolder1$ReportViewer1$ToggleParam$collapse': report_viewer_toggle['value'],
            # 'ctl00$ContentPlaceHolder1$ReportViewer1$ctl07$collapse' : report_viewer_collapse['value'],
            # 'ctl00$ScriptManager1': 'ctl00$ScriptManager1|ctl00$ContentPlaceHolder1$ReportViewer1$ctl09$Reserved_AsyncLoadTarget',
        }

        head = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(timetable_url, data=data, cookies=self.cookies, headers=head)
        with open('response.html', 'w') as file:
            file.write(response.text)

    def _get_attendance(self):
        # The attendance URL looks like
        # https://uims.cuchd.in/UIMS/frmStudentCourseWiseAttendanceSummary.aspx
        attendance_url = AUTHENTICATE_URL + ENDPOINTS["Attendance"]

        # We make an authenticated GET request (by passing the login cookies) to fetch the
        # contents of the attendance page
        # These cookies contain encoded information about the current logged in UID whose
        # attendance information is to be fetched
        response = requests.get(attendance_url, cookies=self.cookies)
        # Checking for error in response as status code returned is 200
        if(response.text.find(ERROR_HEAD) != -1):
            raise UIMSInternalError('UIMS internal error occured')
        # Getting current session id from response
        session_block = response.text.find('CurrentSession')
        session_block_origin = session_block + response.text[session_block:].find('(')
        session_block_end = session_block + response.text[session_block:].find(')')
        current_session_id = response.text[session_block_origin+1:session_block_end]

        if not self._sessionId:
            self._sessionId = current_session_id
        # We now scrape for the uniquely generated report ID for the current UIMS session
        # in the above returned response

        # I have no idea why and what purpose this report ID serves, but this field needed to
        # fetch the attendance in JSON format in the next step as you'll see, otherwise the
        # server will return an error response
        js_report_block = response.text.find("getReport")
        initial_quotation_mark = js_report_block + response.text[js_report_block:].find ("'")
        ending_quotation_mark = initial_quotation_mark + response.text[initial_quotation_mark+1:].find("'")
        report_id = response.text[initial_quotation_mark+1 : ending_quotation_mark+1]

        if not self._reportId:
            self._reportId = report_id
        # On intercepting the requests made by my browser, I found that this URL returns the
        # attendance information in JSON format
        report_url = attendance_url + "/GetReport"

        # This attendance information in JSON format is exactly what we need, and it is possible
        # to replicate the web-browser intercepted request using python requests by passing
        # the following fields        
        data = "{UID:'" + report_id + "',Session:'" + current_session_id + "'}"
        response = requests.post(report_url, headers=headers, data=data)
        # We then return the extracted JSON content
        attendance = json.loads(response.text)["d"]
        return json.loads(attendance)