# *-* coding: UTF-8 *-*

# standard library imports
import logging
import re
import pytz #@UnresolvedImport
import os
# related third party imports
import webapp2
from webapp2_extras import jinja2
from webapp2_extras import auth
from webapp2_extras import sessions
# local application/library specific imports
from bp_includes import models
from bp_includes.lib import utils, i18n, jinja_bootstrap
from babel import Locale #@UnresolvedImport


class ViewClass:
    """
        ViewClass to insert variables into the template.

        ViewClass is used in BaseHandler to promote variables automatically that can be used
        in jinja2 templates.
        Use case in a BaseHandler Class:
            self.view.var1 = "hello"
            self.view.array = [1, 2, 3]
            self.view.dict = dict(a="abc", b="bcd")
        Can be accessed in the template by just using the variables liek {{var1}} or {{dict.b}}
    """
    pass


class BaseHandler(webapp2.RequestHandler):
    """
        BaseHandler for all requests

        Holds the auth and session properties so they
        are reachable for all requests
    """

    def __init__(self, request, response):
        """ Override the initialiser in order to set the language.
        """
        self.initialize(request, response)
        self.view = ViewClass()
        self.localeStrings = i18n.getLocaleStrings(self) # getLocaleStrings() must be called before setting path_qs in render_template()

    def dispatch(self):
        """
            Get a session store for this request.
        """
        self.session_store = sessions.get_store(request=self.request)

        try:# csrf protection
            if self.request.method == "POST" and not self.request.path.startswith('/taskqueue'):
                token = self.session.get('_csrf_token')
                if not token or token != self.request.get('_csrf_token'):
                    self.abort(403)

            # Dispatch the request.
            webapp2.RequestHandler.dispatch(self)
        finally:
            # Save all sessions.
            self.session_store.save_sessions(self.response)

    def logVisit(_s, ukey):
        if _s.app.config['log_visit']:
            try:
                logVisit = models.LogVisit ( user=ukey
                                           , uastring=_s.request.user_agent
                                           , ip=_s.request.remote_addr
                                           , timestamp=utils.get_date_time()
                                           )
                logVisit.put()
            except (apiproxy_errors.OverQuotaError, BadValueError):
                logging.error("Error saving Visit Log in datastore")

    @webapp2.cached_property
    def user_model(self):
        """Returns the implementation of the user model.

        Keep consistency when config['webapp2_extras.auth']['user_model'] is set.
        """
        return self.auth.store.user_model

    @webapp2.cached_property
    def auth(_s):
        return auth.get_auth()

    @webapp2.cached_property
    def session_store(self):
        return sessions.get_store(request=self.request)

    @webapp2.cached_property
    def session(self):
        # Returns a session using the default cookie key.
        return self.session_store.get_session()

    def flash(_s, level, message):
        _s.session.add_flash(message, level, key='_messages')
        return os.environ['theme']

    @webapp2.cached_property
    def get_theme(self):
        return os.environ['theme']

    @webapp2.cached_property
    def auth_config(_s):
        """ Dict to hold urls for login/logout
        """
        return  { 'login_url' : _s.uri_for('login')
                , 'logout_url': _s.uri_for('logout')
                }

    @webapp2.cached_property
    def user(self):
        return self.auth.get_user_by_session()

    @webapp2.cached_property
    def user_id(self):
        return str(self.user['user_id']) if self.user else None

    @webapp2.cached_property
    def user_key(self):
        if self.user:
            user_info = self.user_model.get_by_id(long(self.user_id))
            return user_info.key
        return None

    @webapp2.cached_property
    def username(self):
        if self.user:
            try:
                user_info = self.user_model.get_by_id(long(self.user_id))
                if not user_info.activated:
                    self.auth.unset_session()
                    self.redirect_to('home')
                else:
                    return str(user_info.username)
            except AttributeError, e:
                # avoid AttributeError when the session was deleted from the server
                logging.error(e)
                self.auth.unset_session()
                self.redirect_to('home')
        return None

    @webapp2.cached_property
    def email(self):
        if self.user:
            try:
                user_info = self.user_model.get_by_id(long(self.user_id))
                return user_info.email
            except AttributeError, e:
                # avoid AttributeError when the session was deleted from the server
                logging.error(e)
                self.auth.unset_session()
                self.redirect_to('home')
        return None

    @webapp2.cached_property
    def provider_uris(self):
        login_urls = {}
        continue_url = self.request.get('continue_url')
        for provider in self.provider_info:
            if continue_url:
                login_url = self.uri_for("social-login", provider_name=provider, continue_url=continue_url)
            else:
                login_url = self.uri_for("social-login", provider_name=provider)
            login_urls[provider] = login_url
        return login_urls

    @webapp2.cached_property
    def provider_info(self):
        return models.SocialUser.PROVIDERS_INFO
        
    @webapp2.cached_property
    def tz(self):
        tz = [(tz, tz.replace('_', ' ')) for tz in pytz.all_timezones]
        tz.insert(0, ("", ""))
        return tz

    @webapp2.cached_property
    def get_user_tz(self):
        user = self.current_user
        if user:
            if hasattr(user, 'tz') and user.tz:
                return pytz.timezone(user.tz)
        return pytz.timezone('UTC')

    @webapp2.cached_property
    def countries(self):
        return Locale.parse(self.localeStrings.tag).territories

    @webapp2.cached_property
    def countries_tuple(self):
        countries = self.countries
        if "001" in countries:
            del (countries["001"])
        countries = [(key, countries[key]) for key in countries]
        countries.append(("", ""))
        countries.sort(key=lambda tup: tup[1])
        return countries

    @webapp2.cached_property
    def current_user(self):
        user = self.auth.get_user_by_session()
        if user:
            return self.user_model.get_by_id(user['user_id'])
        return None

    @webapp2.cached_property
    def is_mobile(self):
        return utils.set_device_cookie_and_return_bool(self)

    @webapp2.cached_property
    def jinja2(self):
        return jinja2.get_jinja2(factory=jinja_bootstrap.jinja2_factory, app=self.app)

    @webapp2.cached_property
    def get_base_layout(self):
        """
        Get the current base layout template for jinja2 templating. Uses the variable base_layout set in config
        or if there is a base_layout defined, use the base_layout.
        """
        return self.base_layout if hasattr(self, 'base_layout') else self.app.config.get('base_layout')

    def set_base_layout(self, layout):
        """
        Set the base_layout variable, thereby overwriting the default layout template name in config.py.
        """
        self.base_layout = layout

    def render_template(self, filename, **kwargs):

        path_qs = self.request.path_qs
        if len(self.request.GET) == 0:
            path_qs = path_qs + "?"
        #ToDo: Why cant we just pass back request.path + '?' ?
        # why do we need to pass back the (remainder of) query string too?
            
        # make all self.view variables available in jinja2 templates
        if hasattr(self, 'view'):
            kwargs.update(self.view.__dict__)
        
        # set or overwrite special vars for jinja templates
        kwargs.update({
            'google_analytics_code': self.app.config.get('google_analytics_code'),
            'app_name': self.app.config.get('app_name'),
            'theme': self.get_theme,
            'user_id':  self.user_id,
            'username': self.username,
            'email':    self.email,
            'url':      self.request.url,
            'path':     self.request.path,
            'path_qs':  path_qs, 
            'is_mobile': self.is_mobile,
            'locale_strings': self.localeStrings,
            'provider_uris':  self.provider_uris,
            'provider_info':  self.provider_info,
            'enable_federated_login': self.app.config.get('enable_federated_login'),
            'base_layout': self.get_base_layout
        })
        kwargs.update(self.auth_config)
        if hasattr(self, 'form'):
            kwargs['form'] = self.form
        
        flashMessages = self.session.get_flashes(key='_messages')
        if flashMessages:
            kwargs['messages'] = flashMessages

        self.response.headers.add_header('X-UA-Compatible', 'IE=Edge,chrome=1')
        self.response.write(self.jinja2.render_template(filename, **kwargs))
