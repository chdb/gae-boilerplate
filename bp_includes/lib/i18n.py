import re
import logging
from google.appengine.api.urlfetch_errors import DownloadError
from google.appengine.api import urlfetch
from google.appengine.api import memcache
from webapp2_extras import i18n
from babel import Locale

SixMonths = 26*7*24*60*60 # 26 weeks in seconds

# RE pattern for a language tag plus optional qvalue 
# In w3.org notation:   language-tag [ ";" "q" "=" qvalue ]
# eg:                   "es-ES  ;  q  =  0.123"
AcceptLang_REPattern = r"([a-zA-Z]{1,8}(-[a-zA-Z0-9]{1,8})?)\s*(;\s*q\s*=\s*((1|0)(\.[0-9]+)?))?"
# Capture 2 groups:     (language-tag) and (qvalue)
# group number:          1                  4

def parse_accept_language_header(string, pattern=AcceptLang_REPattern):
    """ Parse a dict from an Accept-Language header string
    (see http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html)
    example input: en-US,en;q=0.8,es-es;q=0.5
    example output: {'en_US': 100, 'en': 80, 'es_ES': 50}
    """
    res = {}
    if not string: return None
    for match in re.finditer(pattern, string):
        if None == match.group(4):  # if these theres no qvalue expression then q = 1
            q = 1
        else:
            q = match.group(4)
        
        l = match.group(1).replace('-','_')
        
        if len(l) == 2:
            l = l.lower()
        elif len(l) == 5:
            la = l.split('_')
            l = la[0].lower() + "_" + la[1].upper()
        else:
            l = None
        
        if l:
            res[l] = int(100*float(q))
    return res

# def get_territory_from_ip(rh):
    # """
    # call: get_territory_from_ip(self.request)

    # Detect the territory code derived from IP Address location
    # Returns US, CA, CL, AR, etc.
    # rh: webapp2.RequestHandler
    
    # Uses lookup service http://geoip.wtanaka.com/cc/<ip>
    # You can get a flag image given the returned territory 
        # with http://geoip.wtanaka.com/flag/<territory>.gif
        # example: http://geoip.wtanaka.com/flag/us.gif
    # """
    # ter = rh.request.cookies.get('territory', None)
    # if ter is None:
        # try:
            # result = urlfetch.fetch("http://geoip.wtanaka.com/cc/%s" % rh.request.remote_addr, deadline=0.8) # tweak deadline if necessary
            # if result.status_code == 200:
                # fetch = result.content
                # if len(str(fetch)) < 3:
                    # ter = str(fetch).upper()
                    # rh.response.set_cookie('territory', ter, max_age = SixMonths)
                # else:
                    # logging.warning("Oops, geoip.wtanaka.com is not working. Look what it returns: %s" % str(fetch) )
            # else:
                # logging.warning("Oops, geoip.wtanaka.com is not working. Status Code: %s" % str(result.status_code) )
        # except DownloadError:
            # logging.warning("Couldn't resolve http://geoip.wtanaka.com/cc/%s"% rh.request.remote_addr)
    
    # return ter
    

def getRequestLocation(request, field):
    """ :param request: the Request Object
        :param field:   one of these strings: "Country","City","Region","CityLatLong"
        :return:        a detail of the location from which the request originated, according to field param as follows:
                        "Country"   :   the ISO 3166-1 alpha-2 Code of the country
                        "Region"    :   name of the region of the country. EG If Country is "US" then Region "ca" means California not Canada.  
                        "City"      :   name of the city 
                        "CityLatLong":  Lat, Long as a string eg "37.386051,-122.083851"   
    """
    return request.headers.get('X-AppEngine-' + field)


def get_locale_from_accept_header(request, localeTags):
    """ Detect a locale from request.header 'Accept-Language'
    The locale with the highest quality factor (q) that most nearly matches our config.locales is returned.
    rh: webapp2.RequestHandler

    Note that in the future if all User Agents adopt the convention of sorting quality factors in descending order
    then the first can be taken without needing to parse or sort the accept header leading to increased performance.
    (see http://lists.w3.org/Archives/Public/ietf-http-wg/2012AprJun/0473.html)
    """
    header = request.headers.get("Accept-Language", '')
    parsed = parse_accept_language_header(header)
    if parsed is None:
        return None
    pairs_sorted_by_q = sorted(parsed.items(), key=lambda (lang, q): q, reverse=True)
    locale = Locale.negotiate([lang for (lang, q) in pairs_sorted_by_q], request.app.config.get('locales'), sep='_')
    return str(locale)

def set_locale(rh, tag=None):
    """ Retrieve the locale and set it for the app.
        
    rh:     webapp2.RequestHandler
    tag:    a locale tag to set (eg 'en_US') - if not None this is the preferred choice provided its on the list of localeTags
    return: locale tag string
    """
    #ToDo: save the locale tag in the User Model and access it below, before cookies.
    # So a logged-in user consistently get his preferred language.
    # (otherwise they get the choice of whoever last used the same browser)
    # Also whenever logged-on user changes the display language, 
    # she needs to be given a choice "do you want to set this as your preferred language ?"
    # Also preferred language should be on registration form defaulting to current language.
        
    def getLocale(rh, tag):
        """ Retrieve the locale tag from a prioritized list of sources
        NB We cannot return None because there has to be a locale - the app has to be some language or other.
        """
        localeTags = rh.app.config.get('locales')
        if localeTags: 
            # 1. use tag param
            if tag in localeTags:
                return tag
            
            # 2. retrieve locale tag from url query string
            tag = rh.request.get("hl", None)
            if tag:
                qs_items = rh.request.GET
                del qs_items['hl']  # remove the hl item from the qs - it has now been processed 
            if tag in localeTags:
                return tag
                
            # 3. retrieve locale tag from cookie
            tag = rh.request.cookies.get('hl', None)
            if tag in localeTags:
                return tag
                
            # 4. retrieve locale tag from accept language header
            tag = get_locale_from_accept_header(rh.request, localeTags)
            if tag:
                return tag
            
            # 5. detect locale tag from IP address location
            ctry = getRequestLocation(rh.request, 'Country')
            if ctry:
                tag = Locale.negotiate(ctry, localeTags)
                if tag:
                    return tag
               
            # 6. use the 1st member of localeTags
            tag = localeTags[0]
            if tag:
                return tag
         
            # 7. Use this locale if all attempts above have failed.
        return 'en' # NB 'en' is chosen simply because the string literals and comments in this app happen to be in English. Its not because of a bias.
            
    tag = getLocale(rh, tag)
    i18n.get_i18n().set_locale(tag)
    
    # save locale tag in cookie with 26 weeks expiration (in seconds)
    rh.response.set_cookie('hl', tag, max_age = SixMonths)
    return tag
  
    
class LocaleStrings (object):
    """ Once we know the locale language, it makes sense to save the set of locale display strings that are associated with it.
    
    _s.enabled:  Localisation is enabled (ie whether there is a locales list in config with more than 1 member)
    _s.tag    :  The current locale in tag form such as: 'en' or 'fr_CA'.
    _s.this   :  The current locale as a display string eg: French(Canada).
    _s.others :  A list of display-string-lists (dsl) for a given curremt locale
    
    There is one dsl for each locale supported by the app, except the current locale.
    A dsl is a list of 3 strings: Tag-string,  Foreign-string (in current locale),  Native-string (localised)
    eg if current locale is Spanish 'es', a dsl fields could be:
              Tag       Foreign                    Native
           -----------------------------------------------------------------
           [ 'en'    , 'Ingles'                 , 'English'                ]   
        or [ 'en_US' , 'Ingles (Estados Unidos)', 'English (United States)']
    """
    Tag     = 0 # enum values for easily identifying the list index 
    Foreign = 1
    Native  = 2
    
    def __init__(_s, ctag, locale_tags):     # @NoSelf
        
        _s.enabled = locale_tags and len(locale_tags) > 1
        _s.tag = ctag
        _s.others = []
        
        if _s.enabled:
            for lt in locale_tags:
                loc = Locale.parse (lt)
                if lt == ctag:                                                            
                    _s.this = loc.display_name
                else:
                    _s.others.append( [ lt                          # loc described using its tag
                                      , loc.get_display_name (ctag) # loc described using the current locale
                                      , loc.display_name            # loc described using the its own locale aka the "localized" locale
                                      ] ) 
            
def getLocaleStrings (handler):
    ctag = set_locale (handler)  # current locale as a string in form: 'aa' or 'aa_AA'  eg: 'en' or 'fr_CA'
    ls = memcache.get (ctag)     # requests from a user will generally have same locale so it makes sense to hold this in memcache @UndefinedVariable
    if ls is None:               # ... and even more so because also many different users will use same locale (memcache is global to the app)
        locale_tags = handler.app.config.get ('locales')
        ls = LocaleStrings (ctag, locale_tags)
        memcache.add (ctag, ls)  # @UndefinedVariable
    return ls
