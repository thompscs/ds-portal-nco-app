from agavepy.agave import AgaveException, Agave
from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.serializers.json import DjangoJSONEncoder
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from designsafe.apps.workspace.tasks import JobSubmitError, submit_job
from designsafe.apps.notifications.views import get_number_unread_notifications
from designsafe.apps.licenses.models import LICENSE_TYPES
from dsapi.agave.daos import FileManager, shared_with_me
from requests import HTTPError
from urlparse import urlparse
from datetime import datetime
import json
import six
import logging
import urllib

logger = logging.getLogger(__name__)


@login_required
def index(request):
    context = {
        'unreadNotifications': get_number_unread_notifications(request)
    }
    return render(request, 'designsafe/apps/workspace/index.html', context)


def _app_license_type(app_id):
    app_lic_type = app_id.split('-')[0].upper()
    lic_type = next((t[0] for t in LICENSE_TYPES if t[0] == app_lic_type), None)
    return lic_type


@login_required
def call_api(request, service):
    try:
        agave = request.user.agave_oauth.client
        if service == 'apps':
            app_id = request.GET.get('app_id')
            if app_id:
                data = agave.apps.get(appId=app_id)
                lic_type = _app_license_type(app_id)
                data['license'] = {
                    'type': lic_type
                }
                if lic_type is not None:
                    lic = request.user.licenses.filter(license_type=lic_type).first()
                    data['license']['enabled'] = lic is not None

            else:
                public_only = request.GET.get('publicOnly')
                if public_only == 'true':
                    data = agave.apps.list(publicOnly='true')
                else:
                    data = agave.apps.list()

        elif service == 'monitors':
            target = request.GET.get('target')
            ds_admin_client = Agave(api_server=getattr(settings, 'AGAVE_TENANT_BASEURL'), token=getattr(settings, 'AGAVE_SUPER_TOKEN'))
            data = ds_admin_client.monitors.list(target=target)

        elif service == 'meta':
            app_id = request.GET.get('app_id')
            if request.method == 'GET':
                if app_id:
                    data = agave.meta.get(appId=app_id)
                    lic_type = _app_license_type(app_id)
                    data['license'] = {
                        'type': lic_type
                    }
                    if lic_type is not None:
                        lic = request.user.licenses.filter(license_type=lic_type).first()
                        data['license']['enabled'] = lic is not None

                else:
                    query = request.GET.get('q')
                    data = agave.meta.listMetadata(q=query)
            elif request.method == 'POST':
                meta_post = json.loads(request.body)
                meta_uuid = meta_post.get('uuid')

                if meta_uuid:
                    del meta_post['uuid']
                    data = agave.meta.updateMetadata(uuid=meta_uuid, body=meta_post)
                else:
                    data = agave.meta.addMetadata(body=meta_post)
            elif request.method == 'DELETE':
                meta_uuid = request.GET.get('uuid')
                if meta_uuid:
                    data = agave.meta.deleteMetadata(uuid=meta_uuid)

        elif service == 'files':
            system_id = request.GET.get('system_id')
            file_path = request.GET.get('file_path', '')
            special_dir = None
            if system_id == 'designsafe.storage.default':
                if shared_with_me in file_path:
                    special_dir = shared_with_me
                    file_path = '/'.join(file_path.split('/')[2:])

                elif file_path == '':
                    file_path = request.user.username

            file_path = file_path.strip('/')

            if file_path == '':
                file_path = '/'

            logger.debug('Listing "agave://%s/%s"...' % (system_id, file_path))

            # Agave Files call
            # data = agave.files.list(systemId=system_id, filePath=file_path)

            # ElasticSearch call
            try:
                fm = FileManager(agave)
                listing = fm.list_path(system_id=system_id,
                                       path=file_path,
                                       username=request.user.username,
                                       special_dir=special_dir,
                                       is_public=system_id == 'nees.public'
                                       )
                data = [f.to_dict() for f in listing]

                # filter out empty projects
                if system_id == 'nees.public' and file_path == '/':
                    data = [f for f in data if 'projecTitle' in f and
                            not f['projecTitle'].startswith('EMPTY PROJECT')]

                # TODO type of "Shared with me" should be "dir" not "folder"
                for d in data:
                    d.update((k, 'dir') for k, v in six.iteritems(d)
                             if k == 'type' and v == 'folder')

                if special_dir:
                    data = [{
                        'name': '.',
                        'path': special_dir + file_path.strip('/'),
                        'systemId': system_id,
                        'type': 'dir',
                    }] + data
                elif file_path != request.user.username:
                    data = [{
                        'name': '.',
                        'path': file_path,
                        'systemId': system_id,
                        'type': 'dir',
                    }] + data

            except:
                data = []

        elif service == 'jobs':
            if request.method == 'DELETE':
                job_id = request.GET.get('job_id')
                data = agave.jobs.delete(jobId=job_id)
            elif request.method == 'POST':
                job_post = json.loads(request.body)
                job_id = job_post.get('job_id')

                # cancel job / stop job
                if job_id:
                    data = agave.jobs.manage(jobId=job_id, body='{"action":"stop"}')

                # submit job
                elif job_post:

                    # cleaning archive path value
                    if 'archivePath' in job_post:
                        parsed = urlparse(job_post['archivePath'])
                        if parsed.path.startswith('/'):
                            # strip leading '/'
                            archive_path = parsed.path[1:]
                        else:
                            archive_path = parsed.path

                        if not archive_path.startswith(request.user.username):
                            archive_path = '{}/{}'.format(
                                request.user.username, archive_path)

                        job_post['archivePath'] = archive_path

                        if parsed.netloc:
                            job_post['archiveSystem'] = parsed.netloc
                    else:
                        job_post['archivePath'] = \
                            '{}/archive/jobs/{}/${{JOB_NAME}}-${{JOB_ID}}'.format(
                                request.user.username,
                                datetime.now().strftime('%Y-%m-%d'))

                    # check for running licensed apps
                    lic_type = _app_license_type(job_post['appId'])
                    if lic_type is not None:
                        lic = request.user.licenses.filter(license_type=lic_type).first()
                        job_post['parameters']['_license'] = lic.license_as_str()

                    # url encode inputs
                    if job_post['inputs']:
                        for key, value in six.iteritems(job_post['inputs']):
                            parsed = urlparse(value)
                            if parsed.scheme:
                                job_post['inputs'][key] = '{}://{}{}'.format(
                                    parsed.scheme, parsed.netloc, urllib.quote(parsed.path))
                            else:
                                job_post['inputs'][key] = urllib.quote(parsed.path)

                    try:
                        data = submit_job(request, request.user.username, job_post)
                    except JobSubmitError as e:
                        data = e.json()
                        logger.error('Failed to submit job {0}'.format(data))
                        return HttpResponse(json.dumps(data),
                                            content_type='application/json',
                                            status=e.status_code)

                # list jobs (via POST?)
                else:
                    limit = request.GET.get('limit', 10)
                    offset = request.GET.get('offset', 0)
                    data = agave.jobs.list(limit=limit, offset=offset)

            elif request.method == 'GET':
                job_id = request.GET.get('job_id')

                # get specific job info
                if job_id:
                    data = agave.jobs.get(jobId=job_id)
                    q = {"associationIds": job_id}
                    job_meta = agave.meta.listMetadata(q=json.dumps(q))
                    data['_embedded'] = {"metadata": job_meta}

                    archive_system_path = '{}/{}'.format(data['archiveSystem'],
                                                         data['archivePath'])
                    data['archiveUrl'] = reverse(
                        'designsafe_data:data_browser',
                        args=['agave', archive_system_path])

                # list jobs
                else:
                    limit = request.GET.get('limit', 10)
                    offset = request.GET.get('offset', 0)
                    data = agave.jobs.list(limit=limit, offset=offset)
            else:
                return HttpResponse('Unexpected service: %s' % service, status=400)

        else:
            return HttpResponse('Unexpected service: %s' % service, status=400)
    except HTTPError as e:
        logger.error('Failed to execute {0} API call due to HTTPError={1}'.format(
            service, e.message))
        return HttpResponse(json.dumps(e.message),
                            content_type='application/json',
                            status=400)
    except AgaveException as e:
        logger.error('Failed to execute {0} API call due to AgaveException={1}'.format(
            service, e.message))
        return HttpResponse(json.dumps(e.message), content_type='application/json',
                            status=400)
    except Exception as e:
        logger.error('Failed to execute {0} API call due to Exception={1}'.format(
            service, e.message))
        return HttpResponse(
            json.dumps({'status': 'error', 'message': '{}'.format(e.message)}),
            content_type='application/json', status=400)

    return HttpResponse(json.dumps(data, cls=DjangoJSONEncoder),
                        content_type='application/json')
