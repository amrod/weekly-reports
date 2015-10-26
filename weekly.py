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

    def __init__(self, args, api_key, main_project_id, other_tasks_id, tags, rm_url):
        self.redmine = Redmine(rm_url, key=api_key, requests={'verify': False})
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
        """
        Retrieves an issue by ID, checking first in the memory cache. Adds the
         issue to the cache if it was not there.
        :param id: ID of the issue to retrieve.
        :return: The redmine.issue instance retrieved.
        """
        try:
            return self.issue_cache[id]

        except KeyError:
            issue = self.redmine.issue.get(id)
            self.issue_cache[id] = issue
            return issue

    def fetch_project(self, id):
        """
        Retrieves an project by ID, checking first in the memory cache. Adds the
         project to the cache if it was not there.
        :param id: ID of the project to retrieve.
        :return: The redmine.project instance retrieved.
        """
        try:
            return self.project_cache[id]

        except KeyError:
            project = self.redmine.project.get(id)
            self.project_cache[id] = project
            return project

    def get_week_start(self):
        """
        Computes the start date of the current week.
        :return: A datetime object with the computed date.
        """
        return datetime.date.today() - datetime.timedelta(days=self.daynum - 1)

    def get_week_end(self):
        """
        Computes the end date of the current week.
        :return: A datetime object with the computed date.
        """
        return datetime.date.today() + datetime.timedelta(days=7 - self.daynum)

    def get_last_week_start(self):
        """
        Computes the start date of the week immediately before the current.
        :return: A datetime object with the computed date.
        """
        return datetime.date.today() - datetime.timedelta(days=self.daynum + 6)

    def get_last_week_end(self):
        """
        Computes the end date of the week immediately before the current.
        :return: A datetime object with the computed date.
        """
        return datetime.date.today() - datetime.timedelta(days=self.daynum)

    def get_time_entries_range(self, startdate, enddate):
        """
        Retrieves all time entries within the given date range from the
        Redmine server.
        :param startdate: Start date of search.
        :param enddate: End date of search.
        :return: A list of redmine.time_entry objects.
        """
        time_entries = self.redmine.time_entry.filter(from_date=startdate,
                                                      to_date=enddate,
                                                      user_id=self.user.id)
        return [te for te in time_entries]

    def extract_by_id(self, time_entries, ids, resource_name):
        """
        Takes a list of time entries and retrieves the resource indicates
        by resource_name. If the ID of the resource matches one of the IDs
        in the ids list given, the time entry is removed from the list.

        :param time_entries: List of redmine.time_entry objects.
        :param ids: IDs of resources of time entries to remove.
        :param resource_name: Name of the resource to check for in the time
        entries. May be issue or project.
        :return: List of time entries removed from the list.
        """
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
        """
        Generated a dictionary where the keys are the ID of the resource
        described by resource_name (issue or project), and the values are a
        list of time entries that belong to that resource.

        :param time_entries: List of time_entry objects.
        :param resource_name: Name of the resource to group the in the time
                              entries by. May be issue or project.
        :return: The dictionary created.
        """

        rsc_dict = {}
        for te in time_entries:
            rsc = getattr(te, resource_name)
            if rsc.id not in rsc_dict:
                rsc_dict[rsc.id] = []
            rsc_dict[rsc.id].append(te)

        return rsc_dict

    def make_presentables_by_issues_(self, issue_te_dict, include_tagged=False):
        """
        Generates a list of Presentable instances from a dictionary of time
        entries grouped by issue.
        The Presentable's title is the Issue's subject if the issue is linked
        to the main_project, and the project name otherwise.
        The Presentable's subitmes are the comments
        in the time entries linked to the Issues.

        :param issue_te_dict: A dictionary where the keys are issue IDs and
                              the values are lists of time_entry objects.
        :param include_tagged: Flag True or False to include comments that
                               contain tags or not. Defaults to False.
        :return: The list of Presentable objects created.
        """
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
        """
        Generates a list of Presentable instances from a dictionary of time
        entries grouped by issue.
        The Presentable's title is the Issue's subject.
        The Presentable's subitmes are the comments
        in the time entries linked to the Issues.

        :param issue_te_dict: A dictionary where the keys are issue IDs and
                              the values are lists of time_entry objects.
        :param include_tagged: Flag True or False to include comments that
                               contain tags or not. Defaults to False.
        :return: The list of Presentable objects created.
        """
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
        """
        Generates a list of Presentable instances from a dictionary of time
        entries grouped by project. The Presentable subitems are the subjects
        of the issues linked the Projects.

        :param project_te_dict: A dictionary where the keys are project IDs and
                                the values are lists of time_entry objects.
        :return: The list of Presentable objects created.
        """
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
        """
        Generates Presntable instances from the given list of time entries.
        :param time_entries:  A list of redmine.time_entry objects.
        :return: A list of the Presentable objects created.
        """

        entries = []
        for te in time_entries:
            comments = te.comments.strip()
            if comments:
                entry = Presentable(comments)
                entries.append(entry)

        return entries

    def mine_hashtags(self, time_entries):
        """
        Searches the given time entries for tags and adds any new tag to the
        tag_cloud instance variable with a reference tot he time entry object
        that contains it.
        :param time_entries: A list of redmine.time_entry objects.
        :return: None
        """
        for te in time_entries:
            tags = self.tag_regex.findall(te.comments.lower())
            for tag in [t.lower() for t in tags if t.lower() in self.known_tags]:
                if tag not in self.tag_cloud:
                    self.tag_cloud[tag] = []
                self.tag_cloud[tag].append(te)

    def strip_tags(self, text):
        """
        Removes known tags from the given text.
        :param text: Text to search for tags.
        :return: Text with tags removed.
        """
        tags = ['#{}'.format(t) for t in self.tag_regex.findall(text)]

        for tag in tags:
            text = text.replace(tag, '')

        return text.strip()

    def get_completeness_string(self, issue):
        """
        Returns a string describing the completion state of the issue.
        :param issue: Issue instance as returned by Redmine library.
        :return: 'Completed.' or 'In progress.' depending on the issue status.
        """
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
        """
        Generates a report for the week.

        :return: The filename of the report generated.
        """
        if self.last_week:
            startdate = self.get_last_week_start()
            enddate = self.get_last_week_end()
        else:
            startdate = self.get_week_start()
            enddate = self.get_week_end()

        time_entries = self.get_time_entries_range(startdate, enddate)

        for te in time_entries:
            self.fetch_issue(te.issue.id)

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


        with open(filename, 'w') as f:
            f.write(self.mytemplate.render(achievements=main_ach,
                                           other_tasks=other_tasks,
                                           week_number=self.weeknum,
                                           developer=self.user,
                                           tags=tags_dict))

        return filename


class Config(object):
    """
    Wrapper class around ConfigParser. Represents a configuration file.
    """

    def __init__(self, config_file_name):
        self.conf = ConfigParser.SafeConfigParser()

        self.config_file_name = config_file_name
        self.reload_config_file()

    def reload_config_file(self):
        self.conf.read(self.config_file_name)

    def update_config_file(self):
        '''
        Writes the current configuration to the config file and then reloads
        it.
        '''

        with open(self.config_file_name, 'wb') as configfile:
            self.conf.write(configfile)
        self.reload_config_file()

    def put_value(self, option, value, section='GENERAL'):
        """
        Saves the given option-value pair to the config file.
        :param option: Key name to save the value under.
        :param value: The value to save.
        :param section: Section name to save the value under. Defaults to
                        GENERAL
        :return: None
        """
        self.reload_config_file()
        if not self.conf.has_section(section):
            self.conf.add_section(section)
        self.conf.set(section, option, value)
        self.update_config_file()

    def get_value(self, option, section='GENERAL'):
        """
        Retrieves the given option from the given section found in the config
        file. Returns None if the option does not exist.

        :param option: Key name to retrieve from the config file.
        :param section: Section to search under. Defaults to GENERAL
        :return: THe value retrieved, or None if the option key doesn't exist.
        """

        if self.conf.has_section(section) and self.conf.has_option(section, option):
            return self.conf.get(section, option)
        else:
            return None

    def items(self, section):
        return self.conf.items(section)


class Presentable(object):
    """
    Represents a group of issues and its corresponding sub-items to be
    consumed by the templating engine.
    """

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
        subitem = subitem
        if self.normalize(subitem) not in [self.normalize(el) for el in self._subitems]:
            self._subitems.append(subitem)

    def normalize(self, s):
        return s.strip().lower()


def prompt_for_value(key):
    """
    Prompts the user for a value.
    :param key: Name of the value to ask for.
    :return: the value provided by the user.
    """
    prompt = 'Please enter a value for "{}":'
    value = raw_input(prompt.format(key))
    return value


def validate_setting(conf, key, valtype=None):
    """
    Verifies the configuration entry key is of valid format. Prompts user for
     value if key is not found in configuration file and continues to prompt
     until a valid value is provided. Saves the value to the config file.

    :param conf: An instance of the Config class initialized with the
                 configuration file.
    :param key: Key to retrieve from the config file.
    :param valtype: Optional type string of the expected value. May be 'string'
                    or 'int'.
    :return: The value retrieved or provided by the user. May be type int or string.
    """
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
            conf.put_value(key, str(value))
            break
        except ValueError:
            print 'ERROR: The value "{}" is not a valid {}'.format(value, valtype)
            value = None
            continue

    return value


def transfer_api_key(conf, privconf):
    """
    Removes API KEY form main config file and moves it to private config file.
    Temporary function only for transition to private conf file.
    :param conf: An instance of the Config class initialized with the
                 public configuration file.
    :param privcconf: An instance of the Config class initialized with the
                      private configuration file.
    :return: None
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
    rm_url =  validate_setting(conf, 'REDMINE_URL', valtype='string')

    keep_trying = True
    while keep_trying:
        try:
            weekly = Weekly(args=args,
                            api_key=api_key,
                            main_project_id=main_proj_id,
                            other_tasks_id=other_tasks_id,
                            tags=all_tags,
                            rm_url=rm_url)

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
