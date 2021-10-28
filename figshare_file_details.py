#!/usr/bin/env python
'''
The script below includes steps to check particular file status
'''

import hashlib
import json

import requests
from requests.exceptions import HTTPError


BASE_URL = 'https://api.figshare.com/v2/{endpoint}'
TOKEN = '' # paste your personal token here

def raw_issue_request(method, url, data=None, binary=False):
    headers = {'Authorization': 'token '  + TOKEN }
    if data is not None and not binary:
        data = json.dumps(data)
    response = requests.request(method, url, headers=headers, data=data)
    try:
        response.raise_for_status()
        try:
            data = json.loads(response.content)
        except ValueError:
            data = response.content
    except HTTPError as error:
        print('Caught an HTTPError: {}'.format(error))
        print('Body:\n', response.content)
        raise
    return data


def issue_request(method, endpoint, *args, **kwargs):
    return raw_issue_request(method, BASE_URL.format(endpoint=endpoint), *args, **kwargs)


def list_articles():
    result = issue_request('GET', 'account/articles')
    print('Listing current articles:')
    if result:
        print(json.dumps(result, indent=3))
    else:
        print('No articles.')


def list_files_of_article(article_id):
    result = issue_request('GET', 'account/articles/{}/files'.format(article_id))
    print('Listing files for article {}:'.format(article_id))
    if result:
        print(json.dumps(result, indent=3))
    else:
        print('No files.')


def article_file_details(article_id, file_id):
    result = issue_request('GET', 'account/articles/{}/files/{}'.format(article_id, file_id))
    if result:
        print(json.dumps(result, indent=3))

# List all my data items
#list_articles()

# List all files of a data item
#data_item_id = '' # ID of the item of interest
#list_files_of_article(data_item_id)

# List details of a particular file of my data item
#data_item_id = '' # ID of the item of interest
#file_id = '' # ID of the file of interest (within the given data item)
#article_file_details(data_item_id,file_id)
