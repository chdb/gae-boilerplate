# -*- coding: utf-8 -*-

"""
    A real simple app for using webapp2 with auth and session.

    It just covers the basics. Creating a user, login, logout
    and a decorator for protecting certain handlers.

    Routes are setup in routes.py and added in main.py
"""
# standard library imports
import logging
# related third party imports
import webapp2
from google.appengine.ext import ndb
from google.appengine.api import taskqueue
from webapp2_extras.auth import InvalidAuthIdError, InvalidPasswordError
from webapp2_extras.i18n import gettext as _
from bp_includes.external import httpagentparser
# local application/library specific imports
import bp_includes.lib.i18n as i18n
from bp_includes.lib.basehandler import BaseHandler
from bp_includes.lib.decorators import user_required
from bp_includes.lib import captcha, utils
import bp_includes.models as models_boilerplate
import forms as forms


class ContactHandler(BaseHandler):
    """
    Handler for Contact Form
    """

    def get(self):
        """ Returns a simple HTML for contact form """

        if self.user:
            user_info = self.user_model.get_by_id(long(self.user_id))
            if user_info.name or user_info.last_name:
                self.form.name.data = user_info.name + " " + user_info.last_name
            if user_info.email:
                self.form.email.data = user_info.email
        params = {
            "exception": self.request.get('exception')
        }

        return self.render_template('contact.html', **params)

    def post(self):
        """ validate contact form """
        if not self.form.validate():
            return self.get()
            
        user_agent = self.request.user_agent
        exception = self.request.POST.get('exception')
        message = self.form.message.data.strip()
        template_val = {}

        try:
            # parse user_agent to get operating system 
            ua = httpagentparser.detect(user_agent)
            osKey = 'flavor'            if ua.has_key('flavor') else 'os'  # windows uses 'os' while others use 'flavor'
            os = str(ua[osKey]['name']) if "name" in ua[osKey]  else "-"
            if 'version' in ua[osKey]:
                os += ' ' + str(ua[osKey]['version'])
            if 'dist' in ua:
                os += ' ' + str(ua['dist'])

            browser  = str(ua['browser']['name'])    if 'browser' in ua else "-"
            bversion = str(ua['browser']['version']) if 'browser' in ua else "-"

            template_val =  { "name"          : self.form.name.data.strip()
                            , "email"         : self.form.email.data.lower()
                            , "ip"            : self.request.remote_addr
                            , "city"          : i18n.get_city_code(self.request)
                            , "region"        : i18n.get_region_code(self.request)
                            , "country"       : i18n.get_country_code(self.request)
                            , "coordinates"   : i18n.get_city_lat_long(self.request)
                            , "browser"       : browser
                            , "browser_version": bversion
                            , "operating_system": os
                            , "message"       : self.form.message.data.strip()
                            }
        except Exception as e:
            logging.error("error getting user agent info: %s" % e)

        try:
            subject = _("Contact") + " " + self.app.config.get('app_name')
            # exceptions for error pages that redirect to contact
            if exception != "":
                subject = "{} (Exception error: {})".format(subject, exception)

            body_path = "emails/contact.txt"
            body = self.jinja2.render_template(body_path, **template_val)

            email_url = self.uri_for('taskqueue-send-email')
            taskqueue.add(url=email_url, params={
                'to': self.app.config.get('contact_recipient')
                , 'subject': subject
                , 'body': body
                , 'sender': self.app.config.get('contact_sender')
            , })

            self.flash('success', _('Your message was sent successfully.'))
            return self.redirect_to('contact')

        except (AttributeError, KeyError), e:
            logging.error('Error sending contact form: %s' % e)       
            self.flash('error', _('Error sending the message. Please try again later.'))
            return self.redirect_to('contact')

    @webapp2.cached_property
    def form(self):
        return forms.ContactForm(self)


class SecureRequestHandler(BaseHandler):
    """
    Only accessible to users that are logged in
    """

    @user_required
    def get(self, **kwargs):
        user_session = self.user
        user_session_object = self.auth.store.get_session(self.request)

        user_info = self.user_model.get_by_id(long(self.user_id))
        user_info_object = self.auth.store.user_model.get_by_auth_token(
            user_session['user_id'], user_session['token'])

        try:
            params ={ "user_session": user_session
                    , "user_session_object": user_session_object
                    , "user_info": user_info
                    , "user_info_object": user_info_object
                    , "userinfo_logout-url": self.auth_config['logout_url']
                    }
            return self.render_template('secure_zone.html', **params)
        
        except (AttributeError, KeyError), e:
            return "Secure zone error:" + " %s." % e


class DeleteAccountHandler(BaseHandler):

    @user_required
    def get(self, **kwargs):
        chtml = captcha.displayhtml ( public_key=self.app.config.get('captcha_public_key')
                                    , use_ssl=(self.request.scheme == 'https')
                                    , error=None)
        if self.app.config.get('captcha_public_key')  == "PUT_YOUR_RECAPCHA_PUBLIC_KEY_HERE" \
        or self.app.config.get('captcha_private_key') == "PUT_YOUR_RECAPCHA_PUBLIC_KEY_HERE":
            chtml = '<div class="alert alert-error"><strong>Error</strong>' \
                        ': You have to ' \
                            '<a href="http://www.google.com/recaptcha/whyrecaptcha" target="_blank">' \
                                'sign up for API keys' \
                            '</a>' \
                        ' in order to use reCAPTCHA.' \
                    '</div>' \
                    '<input type="hidden" name="recaptcha_challenge_field" value="manual_challenge" />' \
                    '<input type="hidden" name="recaptcha_response_field"  value="manual_challenge" />'
        
        params = { 'captchahtml': chtml }
        return self.render_template('delete_account.html', **params)

    def post(self, **kwargs):
        challenge = self.request.POST.get('recaptcha_challenge_field')
        response  = self.request.POST.get('recaptcha_response_field')
        remote_ip = self.request.remote_addr
        cResponse = captcha.submit  ( challenge
                                    , response
                                    , self.app.config.get('captcha_private_key')
                                    , remote_ip)

        if not cResponse.is_valid:     
            self.flash('error', _('Wrong image verification code. Please try again.')
            return self.redirect_to('delete-account')

        if not self.form.validate() and False:
            return self.get()
        
        password = self.form.password.data.strip()
        try:
            user_info = self.user_model.get_by_id(long(self.user_id))
            auth_id = "own:%s" % user_info.username
            password = utils.hashing(password, self.app.config.get('salt'))

            try:
                # authenticate user by its password
                user = self.user_model.get_by_auth_password(auth_id, password)
                if user:
                    # Delete Social Login
                    for social in models_boilerplate.SocialUser.get_by_user(user_info.key):
                        social.key.delete()

                    user_info.key.delete()
                    ndb.Key("Unique", "User.username:%s"    % user.username).delete_async()
                    ndb.Key("Unique", "User.auth_id:own:%s" % user.username).delete_async()
                    ndb.Key("Unique", "User.email:%s"       % user.email).delete_async()

                    #TODO: Delete UserToken objects

                    self.auth.unset_session()
                    msg = self.flash('success', _("The account has been successfully deleted."))
                    return self.redirect_to('home')

            except (InvalidAuthIdError, InvalidPasswordError), e:
                # Returns error message to self.response.write in the BaseHandler.dispatcher
                self.flash('error', _("Incorrect password! Please enter your current password to change your account settings."))
            return self.redirect_to('delete-account')

        except (AttributeError, TypeError), e:
            self.flash('error', _('Your session has expired.'))
            self.redirect_to('login')

    @webapp2.cached_property
    def form(self):
        return forms.DeleteAccountForm(self)
