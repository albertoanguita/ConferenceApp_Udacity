#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb
from google.net.proto.ProtocolBuffer import ProtocolBufferDecodeError

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionMiniForm
from models import SessionForm
from models import SessionForms
from models import Speaker
from models import SpeakerForm

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
MEMCACHE_FEATURED_SPEAKER_KEY = "RECENT_ANNOUNCEMENTS"
FEATURED_SPEAKER_MESSAGE = ('Featured speaker: %s!!')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": ["Default", "Topic"],
}

SESSION_DEFAULTS = {
    "duration": 0,
    "startTime": "00:00",
}

OPERATORS = {
    'EQ': '=',
    'GT': '>',
    'GTEQ': '>=',
    'LT': '<',
    'LTEQ': '<=',
    'NE': '!='
}

FIELDS = {
    'CITY': 'city',
    'TOPIC': 'topics',
    'MONTH': 'month',
    'MAX_ATTENDEES': 'maxAttendees',
}

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionMiniForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)

SESSIONS_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSIONS_GET_REQUEST_WITH_TYPE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2),
)

SESSIONS_GET_REQUEST_TIME = endpoints.ResourceContainer(
    message_types.VoidMessage,
    maxDuration=messages.IntegerField(1),
)

SESSIONS_GET_REQUEST_PERIOD = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    period=messages.StringField(2),
)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
               allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID,
                                   ANDROID_CLIENT_ID, IOS_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

    # - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in
                request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10],
                                                  "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10],
                                                "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email'
                      )
        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in
                request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
                      http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesCreated',
                      http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[
                self._copyConferenceToForm(conf, getattr(prof, 'displayName'))
                for conf in confs]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"],
                                                   filtr["operator"],
                                                   filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in
                     f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in
                      conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[
                self._copyConferenceToForm(conf, names[conf.organizerUserId])
                for conf in \
                conferences]
        )

    # - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name,
                            getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile  # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

    # - - - Session objects - - - - - - - - - - - - - - - - - - -


    def _copySessionToForm(self, session):
        """Copy relevant fields from Conference to ConferenceForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert dates and times to string; just copy others
                if field.name == 'date' or field.name == 'startTime':
                    setattr(sf, field.name, str(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
        # retrieve speaker information from speakerId
        speaker_key = ndb.Key(Speaker, session.speakerId)
        speaker = speaker_key.get()
        setattr(sf, 'speakerName', getattr(speaker, 'name'))
        setattr(sf, 'speakerEmail', getattr(speaker, 'email'))
        setattr(sf, 'websafeSessionKey', session.key.urlsafe())
        sf.check_initialized()
        return sf

    def _createSessionObject(self, request, websafeConferenceKey):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items

        # check user login
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # check conference exists and user is organizer of conference
        c_key = None
        try:
            c_key = ndb.Key(urlsafe=websafeConferenceKey)
            conf = c_key.get()
        except Exception:
            conf = None
        # c_key = ndb.Key(urlsafe=websafeConferenceKey)
        # conf = c_key.get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % websafeConferenceKey)

        if conf.organizerUserId != user_id:
            raise endpoints.UnauthorizedException(
                'Only conference organizer can add '
                'sessions to this conference')


        # check session name and speaker email are included in the form
        if not request.name:
            raise endpoints.BadRequestException(
                "Session 'name' field required")

        if not request.speakerEmail:
            raise endpoints.BadRequestException("Speaker email field required")

        # retrieve the speaker using the provided speaker email. If not exists,
        # create a new speaker with the provided name and email
        speaker_key = ndb.Key(Speaker, request.speakerEmail)
        speaker = speaker_key.get()
        if not speaker:
            # there is no speaker, try to create it
            # the speaker name is required
            if not request.speakerName:
                raise endpoints.BadRequestException(
                    "Speaker name field required")

            speaker = Speaker()
            speaker.name = request.speakerName
            speaker.email = request.speakerEmail
            speaker.key = speaker_key
            speaker.put()

        # check missing fields and fill them with default values



        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in
                request.all_fields()}
        data['speakerId'] = speaker.email

        # delete extra fields from data
        del data['speakerName']
        del data['speakerEmail']

        # todo
        # add default values for those missing (both data model & outbound Message)
        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]
                setattr(request, df, SESSION_DEFAULTS[df])

        # convert dates from strings to Date objects
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10],
                                             "%Y-%m-%d").date()

        # same with time
        data['startTime'] = datetime.strptime(data['startTime'],
                                              "%H:%M").time()

        # generate Session Key based on conference websafe key and Session

        session_id = Session.allocate_ids(size=1, parent=c_key)[0]
        session_key = ndb.Key(Session, session_id, parent=c_key)
        data['key'] = session_key


        # create Session, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        session = Session(**data)
        session.put()
        # taskqueue.add(params={'email': user.email(),
        #     'conferenceInfo': repr(request)},
        #     url='/tasks/send_confirmation_email'
        # )
        return session

    def _addSessionToWishlist(self, websafeSessionKey):
        # check user login
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        prof = self._getProfileFromUser()

        # check session exists
        try:
            s_key = ndb.Key(urlsafe=websafeSessionKey)
            session = s_key.get()
        except Exception:
            # session does not exist -> 401 error
            raise endpoints.NotFoundException(
                'No session found with key: %s' % websafeSessionKey)

        if websafeSessionKey not in prof.sessionsWishlist:
            # add session to wishlist
            prof.sessionsWishlist.append(websafeSessionKey)
            prof.put()
            return True
        else:
            # the session was already in the users wishlist
            return False

    @endpoints.method(SESSION_POST_REQUEST, SessionForm,
                      path='session/{websafeConferenceKey}',
                      http_method='PUT', name='createSession')
    def createSession(self, request):
        """Create new session."""
        # check other sessions for this speaker


        sessions = Session \
            .query(ancestor=ndb.Key(urlsafe=request.websafeConferenceKey)) \
            .filter(Session.speakerId == request.speakerEmail)


        # sessions = Session.\
        #     query(ancestor=ndb.Key(urlsafe=request.websafeConferenceKey)).\
        #     query(Session.speakerId == request.email)
        featuredSpeaker = False
        if sessions:
            featuredSpeaker = True
        session = self._createSessionObject(request,
                                            request.websafeConferenceKey)
        if featuredSpeaker:
            # add featured speaker to memcache
            speaker = Speaker.query(Speaker.email==request.speakerEmail)
            announcement = FEATURED_SPEAKER_MESSAGE % (speaker.get().name)

            taskqueue.add(
                params={'key': MEMCACHE_ANNOUNCEMENTS_KEY, 'announcement': announcement},
                url='/tasks/set_featured_speaker'
            )



            # memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)

        return self._copySessionToForm(session)

    @endpoints.method(SESSION_GET_REQUEST, SessionForm,
                      path='sessions/key/{sessionKey}',
                      http_method='GET', name='getSessionByKey')
    def getSessionByKey(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        # check session exists
        try:
            # s_key = ndb.Key(urlsafe=websafeSessionKey)
            s_key = ndb.Key(urlsafe=request.sessionKey)
            session = s_key.get()
            return self._copySessionToForm(session)
        except Exception:
            # session does not exist -> 401 error
            raise endpoints.NotFoundException(
                'No session found with key: %s' % request.sessionKey)

    @endpoints.method(SESSIONS_GET_REQUEST, SessionForms,
                      path='sessions/{websafeConferenceKey}',
                      http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        sessions = Session.query(
            ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))
        # return self._copySessionToForm(session)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SESSIONS_GET_REQUEST_WITH_TYPE, SessionForms,
                      path='sessions/{websafeConferenceKey}/{typeOfSession}',
                      http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        sessions = Session \
            .query(ancestor=ndb.Key(urlsafe=request.websafeConferenceKey)) \
            .filter(Session.typeOfSession == request.typeOfSession)
        # return self._copySessionToForm(session)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SpeakerForm, SessionForms,
                      path='sessions',
                      http_method='GET', name='getConferenceSessionsBySpeaker')
    def getConferenceSessionsBySpeaker(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        sessions = Session.query(Session.speakerId == request.email)
        # return self._copySessionToForm(session)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SESSION_GET_REQUEST, BooleanMessage,
                      path='sessions/wishlist/{sessionKey}',
                      http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        return BooleanMessage(
            data=self._addSessionToWishlist(request.sessionKey))
        # sessions = Session.query(Session.speakerId==request.email)
        # # return self._copySessionToForm(session)
        # return SessionForms(
        #     items=[self._copySessionToForm(session) for session in sessions]
        # )

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='sessions/wishlist',
                      http_method='GET', name='getSessionsWishlist')
    def getSessionsWishlist(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        prof = self._getProfileFromUser()  # get user Profile
        session_keys = [ndb.Key(urlsafe=wssk) for wssk in
                        prof.sessionsWishlist]
        sessions = ndb.get_multi(session_keys)
        # return self._copySessionToForm(session)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(message_types.VoidMessage, BooleanMessage,
                      path='sessions/wishlist/clear',
                      http_method='GET', name='clearSessionsWishlist')
    def clearSessionsWishlist(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        prof = self._getProfileFromUser()  # get user Profile
        if prof.sessionsWishlist:
            retVal = True
        else:
            retVal = False
        prof.sessionsWishlist = []
        prof.put()
        # return self._copySessionToForm(session)
        return BooleanMessage(data=retVal)

    @endpoints.method(SESSIONS_GET_REQUEST_TIME, SessionForms,
                      path='sessions/time',
                      http_method='GET', name='getMaxTimeSessions')
    def getMaxTimeSessions(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        # check session exists
        sessions = Session.query(Session.duration <= request.maxDuration)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SESSIONS_GET_REQUEST_PERIOD, SessionForms,
                      path='sessions/period',
                      http_method='GET', name='getConferenceSessionsInPeriod')
    def getConferenceSessionsInPeriod(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        # check session exists
        # noon = datetime.strptime(data['startTime'], "%H:%M").time()
        noon = datetime.strptime('12:00', "%H:%M").time()
        startEvening = datetime.strptime('18:00', "%H:%M").time()

        sessions = Session.query(
            ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))

        if (request.period == 'morning'):
            sessions = sessions.filter(Session.startTime <= noon)
        elif (request.period == 'afternoon'):
            sessions = sessions.filter(Session.startTime > noon)
            sessions = sessions.filter(Session.startTime <= startEvening)
        elif (request.period == 'evening'):
            sessions = sessions.filter(Session.startTime > startEvening)

        sessions = sessions.order(Session.startTime)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='sessions/nonworkbefsev',
                      http_method='GET', name='queryNonWorkshopsBefore7')
    def queryNonWorkshopsBefore7(self, request):
        """Query all sessions in a conference"""
        # create ancestor query for all key matches for this user
        # check session exists
        # noon = datetime.strptime(data['startTime'], "%H:%M").time()

        nonWorkshops = Session.query(Session.typeOfSession != 'workshop')
        sevenPM = datetime.strptime('19:00', "%H:%M").time()
        # sessionsBefore7 = Session.query(Session.startTime<=sevenPM)

        # return SessionForms(
        #     items=[self._copySessionToForm(session) for session in nonWorkshops if session in sessionsBefore7]
        # )
        return SessionForms(
            items=[self._copySessionToForm(session) for session in nonWorkshops
                   if session.startTime <= sevenPM]
        )

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='sessions/speaker/get',
                      http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return Announcement from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY) or "")

    # - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")

    # - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()  # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in
                     prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in
                      conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[
            self._copyConferenceToForm(conf, names[conf.organizerUserId]) \
            for conf in conferences]
                               )

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground',
                      http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city == "London")
        q = q.filter(Conference.topics == "Medical Innovations")
        q = q.filter(Conference.month == 6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )


api = endpoints.api_server([ConferenceApi])  # register API
