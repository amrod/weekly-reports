# Weekly Reports

This script was a quick-and-dirty solution to an unfortunate reality of corporate life: the Weekly Report. My employer was at least using Redmine, which is a decent project management system. But the weekly report _file_ detailing your activities during that timeframe, emailed to the manager, was still a requirement.
Since my team was already logging time spent in Redmine isses, stories, and so forth, I came up with a quick way of producing a report using that information. 

This was made for Windows users, so the private configuration file is stored in Windows's APPDATA folder. That can be easily changed by updating the `PRIV_CONF_FILE` variabe.
More importantly, your personal Redmine API key is **not stored securely**, so if your Redmine server is publicly-facing you should handle your key more carefuly.

There's a rudimentary tagging system: one tag per report section is supported. You can configure the actual tag text. If a particular tag is found in the description of a time entry, that entry will be displayed under the corresponding section.

### Dependencies

- [Python Redmine](https://github.com/maxtepkeev/python-redmine)
- [Requests](https://github.com/kennethreitz/requests)
- [mako](http://www.makotemplates.org/)
- [py2exe](http://www.py2exe.org/) (_If_ you want to build an exe)

### Bugs

Tags are not always parsed correctly. Someday I'll get around fixing that.

### License

MIT
