# Copyright 2012 Nebula, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from django import shortcuts
import django.views.decorators.vary

import horizon
from horizon import base

from openstack_auth import forms
print "openstack_auth openstack_auth  import forms"

def get_user_home(user):
    dashboard = None
    if user.is_superuser:
        try:
            dashboard = horizon.get_dashboard('admin')
        except base.NotRegistered:
            pass

    if dashboard is None:
        dashboard = horizon.get_default_dashboard()
    print u"views dashboard.get_absolute_url(): %s" % (dashboard.get_absolute_url())

    return dashboard.get_absolute_url()


@django.views.decorators.vary.vary_on_cookie
def splash(request):
    if request.user.is_authenticated():
        response = shortcuts.redirect(horizon.get_user_home(request.user))
    else:
        print dir(request)
        form = forms.Login(request)
        print "views.splash nologin"
        print dir(form)
        print "form list end."
        print (form.visible_fields)
        print "visible_fields end."
        request.session.clear()
        request.session.set_test_cookie()
        response = shortcuts.render(request, 'splash.html', {'form': form})
        #print dir(response)
        #print "response end."
    response.delete_cookie('logout_reason')
    print u"request: %s" % (request)

    return response
