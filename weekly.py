__author__ = 'amrodriguez'

import datetime
import os
import re
import sys
import webbrowser
import ConfigParser
import argparse
import path
import requests.packages.urllib3
from redmine import Redmine
from redmine import exceptions as rm_exceptions
from requests import exceptions as req_exceptions
from mako.template import Template

requests.packages.urllib3.disable_warnings()

if hasattr(sys, "frozen") and sys.frozen in ("windows_exe", "console_exe"):
    app_path = path.path(os.path.abspath(sys.executable)).dirname()
else:
    app_path = os.path.dirname(os.path.realpath(__file__))

CONFIG_FILE = os.path.join(app_path, 'weekly.ini')
PRIV_CONF_FILE = os.path.join(os.getenv('APPDATA'), 'weekly.conf')


class Weekly(object):

    def __init__(self, args, api_key, main_project_id, other_tasks_id, tags):
        self.redmine = Redmine('https://cpcgmine.gemalto.com', key=api_key, requests={'verify': False})
        self.user = self.redmine.user.get('current')
        self.weeknum, self.daynum = datetime.date.today().isocalendar()[1:]
        self.mytemplate = Template(filename='template.htm',
                                   module_directory=os.getenv('Temp'),
                                   default_filters=['decode.utf8'],
                                   input_encoding='utf-8',
                                   output_encoding='utf-8')

        self.last_week = args.last_week
        if self.last_week:
            self.weeknum -= 1

        self.main_project_id = main_project_id
        self.other_tasks_id = other_tasks_id

        self.known_tags = [t.lower() for t in tags]
        self.project_cache = {}
        self.issue_cache = {}
        self.tag_cloud = {}

        self.tag_regex = re.compile(r'.*#(\w+)')

    def fetch_issue(self, id):
        try:
            return self.issue_cache[id]

        except KeyError:
            issue = self.redmine.issue.get(id)
            self.issue_cache[id] = issue
            return issue

    def fetch_project(self, id):
        try:
            return self.project_cache[id]

        except KeyError:
            project = self.redmine.project.get(id)
            self.project_cache[id] = project
            return project

    def get_week_start(self):
        return datetime.date.today() - datetime.timedelta(days=self.daynum - 1)

    def get_week_end(self):
        return datetime.date.today() + datetime.timedelta(days=7 - self.daynum)

    def get_last_week_start(self):
        return datetime.date.today() - datetime.timedelta(days=self.daynum + 6)

    def get_last_week_end(self):
        return datetime.date.today() - datetime.timedelta(days=self.daynum)

    def get_time_entries_range(self, startdate, enddate):
        time_entries = self.redmine.time_entry.filter(from_date=startdate, to_date=enddate, user_id=self.user.id)
        return [te for te in time_entries]

    def extract_by_id(self, time_entries, ids, resource_name):

        if not hasattr(ids, '__contains__'):
            ids = [ids]

        filtered = []
        for te in time_entries[:]:
            rsc = getattr(te, resource_name)
            if rsc.id in ids:
                filtered.append(te)
                time_entries.remove(te)

        return filtered

    def mk_dict_by_rsc_type(self, time_entries, resource_name):

        rsc_dict = {}
        for te in time_entries:
            rsc = getattr(te, resource_name)
            if rsc.id not in rsc_dict:
                rsc_dict[rsc.id] = []
            rsc_dict[rsc.id].append(te)

        return rsc_dict

    def make_presentables_by_issues_(self, issue_te_dict, include_tagged=False):

        items = []
        for issue_id, issue_te_dict in issue_te_dict.items():
            item = Presentable()
            rm_issue = self.fetch_issue(issue_id)
            if rm_issue.project.id == self.main_project_id:
                item.title = u'{}: <b><i>{}</i></b>'.format(rm_issue.subject, self.get_completeness_string(rm_issue))
            else:
                rm_proj = self.fetch_project(rm_issue.project.id)
                item.title = rm_proj.name

            for te in issue_te_dict:
                comments = self.strip_tags(te.comments)
                if comments:
                    if include_tagged or not self.is_in_tag_cloud(te):
                        item.add_subitem(comments)
            items.append(item)

        return items

    def make_presentables_by_issue(self, issue_te_dict, include_tagged=False):

        items = []
        for issue_id, issue_te_dict in issue_te_dict.items():
            issue = Presentable()
            rm_issue = self.fetch_issue(issue_id)
            issue.title = u'{}: <b><i>{}</i></b>'.format(rm_issue.subject, self.get_completeness_string(rm_issue))

            for te in issue_te_dict:
                comments = self.strip_tags(te.comments)
                if comments:
                    if include_tagged or not self.is_in_tag_cloud(te):
                        issue.add_subitem(comments)
            items.append(issue)

        return items

    def make_presentables_by_project(self, project_te_dict):

        projects = []
        for project_id, time_entries in project_te_dict.items():
            project = Presentable()
            rm_proj = self.fetch_project(project_id)
            project.title = rm_proj.name

            issues_dict = self.mk_dict_by_rsc_type(time_entries, 'issue')

            for issue_id, te in issues_dict.items():
                rm_issue = self.fetch_issue(issue_id)
                project.add_subitem(rm_issue.subject)

            projects.append(project)

        return projects

    def mk_pres_obj_from_time_entries(self, time_entries):

        entries = []
        for te in time_entries:
            comments = te.comments.strip()
            if comments:
                entry = Presentable(comments)
                entries.append(entry)

        return entries

    def mine_hashtags(self, time_entries):
        for te in time_entries:
            tags = self.tag_regex.findall(te.comments.lower())
            for tag in [t.lower() for t in tags if t.lower() in self.known_tags]:
                if tag not in self.tag_cloud:
                    self.tag_cloud[tag] = []
                self.tag_cloud[tag].append(te)

    def strip_tags(self, text):
        tags = ['#{}'.format(t) for t in self.tag_regex.findall(text)]

        for tag in tags:
            text = text.replace(tag, '')

        return text.strip()

    def get_completeness_string(self, issue):
        if issue.done_ratio == 100 or unicode(issue.status).lower() == 'done':
            return u'Completed.'
        else:
            return u'In progress.'

    def is_in_tag_cloud(self, time_entry):
        for tagged in self.tag_cloud.values():
            if time_entry in tagged:
                return True

        return False

    def report_week(self):
        if self.last_week:
            startdate = self.get_last_week_start()
            enddate = self.get_last_week_end()
        else:
            startdate = self.get_week_start()
            enddate = self.get_week_end()

        time_entries = self.get_time_entries_range(startdate, enddate)

        for te in time_entries:
            self.fetch_issue(te.issue.id)

        #for id, issue in self.issue_cache.items():
        #    self.fetch_project(issue.project.id)

        self.mine_hashtags(time_entries)
        other_tasks_te = self.extract_by_id(time_entries, self.other_tasks_id, resource_name='issue')
        main_project_te = self.extract_by_id(time_entries, self.main_project_id, resource_name='project')

        main_project_te_dict = self.mk_dict_by_rsc_type(main_project_te, 'issue')
        everything_else_dict = self.mk_dict_by_rsc_type(time_entries, 'project')
        tags_dict = {}

        for tag, tagged_time_entries in self.tag_cloud.items():
            dict_ = self.mk_dict_by_rsc_type(tagged_time_entries, resource_name='issue')
            tags_dict[tag] = self.make_presentables_by_issues_(dict_, include_tagged=True)

        main_ach = []
        main_ach += self.make_presentables_by_issue(main_project_te_dict)
        main_ach += self.make_presentables_by_project(everything_else_dict)

        other_tasks = self.mk_pres_obj_from_time_entries(other_tasks_te)

        filename = '{}_WeeklyReport_{:02}.html'.format(str(self.user).replace(' ', ''), self.weeknum)


        #for item in main_ach:
        #    for subitem in item.subitems:
        #        print subitem


        with open(filename, 'w') as f:
            f.write(self.mytemplate.render(achievements=main_ach,
                                           other_tasks=other_tasks,
                                           week_number=self.weeknum,
                                           developer=self.user,
                                           tags=tags_dict))

        return filename


class Config(object):
    def __init__(self, config_file_name):
        self.conf = ConfigParser.SafeConfigParser()

        self.config_file_name = config_file_name
        self.reload_config_file()

    def reload_config_file(self):
        self.conf.read(self.config_file_name)

    def update_config_file(self):
        with open(self.config_file_name, 'wb') as configfile:
            self.conf.write(configfile)
        self.reload_config_file()

    def put_value(self, option, value, section='GENERAL'):
        self.reload_config_file()
        if not self.conf.has_section(section):
            self.conf.add_section(section)
        self.conf.set(section, option, value)
        self.update_config_file()

    def get_value(self, option, section='GENERAL'):
        if self.conf.has_section(section) and self.conf.has_option(section, option):
            return self.conf.get(section, option)
        else:
            return None

    def items(self, section):
        return self.conf.items(section)


class Presentable(object):

    def __init__(self, title=None):
        self._subitems = []
        self._title = title

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, title):
        self._title = title

    @property
    def subitems(self):
        return self._subitems

    def add_subitem(self, subitem):
        subitem = subitem  #.replace(u'\xa0', u' ')
        if self.normalize(subitem) not in [self.normalize(el) for el in self._subitems]:
            self._subitems.append(subitem)

    def normalize(self, s):
        return s.strip().lower()


def prompt_for_value(key):
    prompt = 'Please enter a value for "{}":'
    value = raw_input(prompt.format(key))
    return value


def validate_setting(conf, key, valtype=None):

    if not valtype:
        valtype = 'string'

    cast_func = str
    if valtype == 'string':
        cast_func = str
    if valtype == 'int':
        cast_func = int

    value = conf.get_value(option=key)

    while True:
        if not value:
            value = prompt_for_value(key)
        try:
            value = cast_func(value)
            break
        except ValueError:
            print 'ERROR: The value "{}" is not a valid {}'.format(value, valtype)
            value = None
            continue

    conf.put_value(key, str(value))

    return value


def transfer_api_key(conf, privcconf):
    """
    Removes API KEY form main config file and moves it to private config file.
    Temporary function only for transition to private conf file.
    :param conf:
    :param privcconf:
    :return:
    """
    old_apikey = conf.get_value(option='API_KEY')

    if old_apikey:
        privconf.put_value('API_KEY', old_apikey)
        conf.remove_option('GENERAL', 'API_KEY')
        conf.update_config_file()
        privconf.update_config_file()

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--last-week', action='store_true', help='Retrieve report from last week.')
    args = parser.parse_args()

    privconf = Config(PRIV_CONF_FILE)
    conf = Config(CONFIG_FILE)

    transfer_api_key(conf, privconf)

    api_key = validate_setting(privconf, 'API_KEY')
    main_proj_id = validate_setting(conf, 'MAIN_PROJECT_ID', valtype='int')
    other_tasks_id = validate_setting(conf, 'OTHER_TASKS_ID', valtype='int')
    all_tags = dict(conf.items('TAGS')).values()

    keep_trying = True
    while keep_trying:
        try:
            weekly = Weekly(args=args, api_key=api_key, main_project_id=main_proj_id, other_tasks_id=other_tasks_id, tags=all_tags)
            rpt_name = weekly.report_week()
            webbrowser.open(rpt_name)
            break
        except rm_exceptions.AuthError:
            print 'Invalid API KEY. Enter a new value or leave empty to exit.'
            privconf.put_value('API_KEY', '')
            api_key = validate_setting(privconf, 'API_KEY')
            if not api_key:
                keep_trying = False
        except req_exceptions.ConnectionError:
            print 'Connection error. Please try again later.'
            keep_trying = False
