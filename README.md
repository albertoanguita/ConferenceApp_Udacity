# Conference organization app

A conference organization app hosted in Google App Engine for the Fullstack nanodegree at Udacity


## Index of contents

1. General description
2. Running the application
3. Description of files 
4. Implemented features


## General description

The project extends the conference organization app provided by the instructors.

The app has been deployed in Google App Engine and tested through its backend services.

my app id: **myconferenceapp-1055**


## Running the application

The application must be deployed in Google's App Engine in order to run, as seen in class.

The application is already running in my google account, and is hosted at:

https://myconferenceapp-1055.appspot.com                  (for front end interface)

https://myconferenceapp-1055.appspot.com/_ah/api/explorer (for services interface)

To deploy the code in your own google app, several strings must be modified:

1. In app.yaml, replace the app id for your app id **(line1)**
2. In settings.py, replace the value of `WEB_CLIENT_ID` for your own client id **(line 15)**
3. In js/app.js, replace the value of `CLIENT_ID` for your own client id **(line 89)**

And use Google App Engine Launcher to deploy the code.


##Description of files

The app code is contained within the ConferenceCentral_Complete directory.

The list below describes the files **that have been modified** with respect the code provided by the instructors:

* **app.yaml**: contains app general information and definitions of accepted URLs.
* **conference.py**: contains the implementation of the app endpoints.
* **index.yaml**: contains definitions of indexes for the Datastore.
* **main.py**: implementations of some private tasks
* **models.py**: definition of Datastore kinds and ProtoRPC messages.


## Implemented features

All basic and optional features have been implemented. The text below describes the solutions implemented for each project task, including references to code.

### Task 1: Add Sessions to a Conference

This task involved the definition of kinds and ProtoRPC messages in models.py and endpoints in conference.py for generating, storing and retrieving entities of those kinds.

* **Kind definition**

Two kinds were defined: **Session (models.py, 113)** and **Speaker (models.py, 172)**. Session defines the information of a single conference session, while Speaker identifies one person that will speak in a session.

The Session kind contains the attributes described in the project instructions: name (required, must be unique), highlights (repeated), duration (in minutes), typeOfSession, date and startTime. 
In addition, the speaker email, which uniquely identifies speakers, is stored. 
The types selected for these fields are detailed below:

* name: ndb.StringProperty(required=True). The name is stored as a string, and is mandatory for all sessions
* highlights: ndb.StringProperty(repeated=True). Highlights are individual works describing the session, so we use again a StringProperty. In this case, a list of StringProperties.
* speakerId: ndb.StringProperty(). the speakerId is the email of the speaker, which uniquely identifies her/him. Therefore, it is stored as a StringProperty.
* duration: ndb.IntegerProperty(). The duration indicates the number of minutes that the sessions lasts. We use an IntegerProperty to store those minutes. The code will set a default of 0 if no value is specified.
* typeOfSession: ndb.StringProperty(). The type of session is a keyword that indicates what kind of session is being hosted (e.g. lecture, workshop...). A StringProperty is valid for storing this value.
* date: ndb.DateProperty(). The date at which the session takes place. The DateProperty is the appropriate type for storing this value.
* startTime: ndb.TimeProperty(). The time of the day at which the session starts. We will only store hour and minutes, in 24h format. The TimeProperty allows us to store this value. A default value of 00:00 is set if startTime is not specified. 

The Speaker kind contains two attributes: name and email. Email acts as id for generating entity keys. Below, the detail of the types selected for these fields.

* name: ndb.StringProperty(required=True). As in session, the name of the speaker is stored using a StringProperty. This value is required.
* email: ndb.StringProperty(required=True). This value is also stored as a StringProperty, and is also required. Email values act as speaker identifiers, and are used to generate speaker entities keys.


* **ProtoRPC messages definition**

For session, two different protoRPC messages are defined: SessionMiniForm **(models.py, 135)** and SessionForm **(models.py, 149)**. 
The former is used to submit data of new sessions (does not include conference key nor sesssion key). 
The latter is used as return message when retrieving sessions from the database.

For speaker, one protoRPC message is defined: SpeakerForm **(models.py, 180)**. It contains the same fields as its equivalent kind: name and email.


* **Endpoints definition**

First, two helper methods were defined: `_copySessionToForm(session)` **(conference.py, 458)**, and `_createSessionObject(request, websafeConferenceKey)` **(conference.py, 477)**. 

The first receives a Session entity, and returns an equivalent SessionForm message.

The second creates a new Session entity from a SessionMiniForm message and a conference key. 
The user login is checked. The code checks that the provided conference key corresponds to an existing conference, and that the user is the creator of the conference. Also, the speaker email received in the request is checked in the Datastore. If no speaker with that email exists, the new speaker entity is created. In this case, the speaker mail is required (otherwise, only the speaker email is necessary). 
Default values for duration (0) and startTime (00:00) are set is these are missing in the request. Dates and times are parsed. A new session id is generated, using the conference key as parent (so that the session is a child of the conference)

Next, the requested endpoints are implemented. 

`createSession(SessionForm, websafeConferenceKey)` **(conference.py, 599)**: creates a new session from a SessionMiniForm and a conference key

`getConferenceSessions(websafeConferenceKey)` **(conference.py, 630)**: performs an ancestor query with the conference key to retrieve sessions in that conference

`getConferenceSessionsByType(websafeConferenceKey, typeOfSession)` **(conference.py, 643)**: the ancestor query from the previous method is expanced with a filter that states the value for typeOfSession

`getSessionsBySpeaker(speaker)` **(conference.py, 657)**: a simple query filtering the speakerId is performed. This id must match the email value submitted in the request.


* **Design choices**

I decided to create a session kind and a separate speaker kind to be able to provide detailed information about speakers. By storing the speaker email under the speakerId field of Session, we ensure that the session entities have access to their corresponding speaker entity. Several sessions can share the speaker, simply by storing the same email value in their speakerId field. The speaker entity could be expanded with additional fields that provide further information about the speaker.


### Task 2: Add Sessions to User Wishlist

For this task, I modified the Profile kind in models.py **(30)**, adding a new field `sessionsWishlist` that stores the list of sessions websafekeys that the user is interested in. The ProfileForm also incorporates this field, in case these data are to be displayed in the user profile.

Then, I added one helper method in conference.py:

`_addSessionToWishlist(SessionKey)` **(conference.py, 569)**: retrieves the user's profile and adds the provided session key to the sessionsWishlist field. Stores the profile again.

Finally, I added two new endpoints in conference.py:

`addSessionToWishlist(SessionKey)` **(conference.py, 670)**: invokes the previous method to add the session to the user's wishlist. Returns a Boolean message indicating if the session was stored in the wishlist.

`getSessionsWishlist(SessionKey)` **(conference.py, 679)**: retrieves the sessions previously added to the user's wishlist

In addition, I created an endpoint for clearing the user's wishlist, to facilitate testing (clearSessionsWishlist(), conference.py, 698)

### Task 3: Work on indexes and queries

**Additional queries**: I defined two new endpoints that implement new queries over the data:

`getMaxTimeSessions(maxDuration)` **(conference.py, 719)**: queries stored sessions and retrieves those that last less or equal than the value provided. This query **does not** require an index

`getConferenceSessionsInPeriod(websafeConferenceKey, period)` **(conference.py, 731)**: queries sessions of the given conference and selects the ones in the provided period of day. 
The parameter period can take the values 'morning' (for sessions before noon), 'afternoon' (for sessions between noon and 6pm), and evening (for sessions after 6pm). If it takes any other value, it will return all sessions in the conference.
This query **does** require a new index, since it queries by ancestor and includes an inequality in startTime. The added index is located in index.yaml (98):

```
- kind: Session
  ancestor: yes
  properties:
  - name: startTime
```

**The query problem**

The problem with a query for non workshop sessions that start before 7pm is that it would contain two inequalities, and that is forbidden by the App Engine.

I thought of two ways to solve this problem:

1. Query non workshops only. Then filter the results and exclude the post 7pm values with pure Python code.
This solution is implemented in the endpoint queryNonWorkshopsBefore7_1 **(conference.py, 759)**

2. Perform a query for non workshops only, and perform a second query for sessions before 7pm. Then perform the intersection of the two resultsets in Python.
This solution is implemented in the endpoint queryNonWorkshopsBefore7_2 **(conference.py, 776)**
While this solution is somewhat more elegant from the design point of view (filtering is done by the database, not by the code) it involves two queries instead of one, and the intersection of lists involves O(n^2) complexity.


### Task 4: Add a Task

The endpoint `createSession` was modified **(conference.py, 599)** to create a task when it detects that there is a new featured speaker. 
This condition is met simply when the speaker was already present in an existing session of the same conference.

When the code detects a featured speaker, it generates a new task and adds it to the default task queue. The task implementation is 
in the main.py method (line 42). This method adds a new entry in the memcache, with key 'FEATURED_SPEAKER'.

app.yaml was also modified to redirect to this implementation, given the URL (line 36).

the endpoint 'getFeaturedSpeaker' was added to conferences.py (line 795) to retrieve the memcache entry added by the previous task.
