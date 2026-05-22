#!/bin/bash
# 1. Remove .env file from the current commit
rm -f .env

# 2. Replace sensitive strings in all tracked files
find . -type f -not -path "./.git/*" -exec sed -i \
    -e "s/REDACTED_APP_ID/REDACTED_APP_ID/g" \
    -e "s/REDACTED_APP_SECRET/REDACTED_APP_SECRET/g" \
    -e "s/REDACTED_RECEIVE_ID/REDACTED_RECEIVE_ID/g" \
    -e "s/REDACTED_WF_KEY_1/REDACTED_WF_KEY_1/g" \
    -e "s/REDACTED_WF_KEY_2/REDACTED_WF_KEY_2/g" \
    -e "s/REDACTED_WF_KEY_3/REDACTED_WF_KEY_3/g" \
    -e "s/REDACTED_WF_KEY_4/REDACTED_WF_KEY_4/g" \
    -e "s/REDACTED_WF_KEY_5/REDACTED_WF_KEY_5/g" \
    -e "s/REDACTED_FACE_API_KEY/REDACTED_FACE_API_KEY/g" \
    -e "s/REDACTED_PASSWORD/REDACTED_PASSWORD/g" \
    -e "s/REDACTED_ID_1/REDACTED_ID_1/g" \
    -e "s/REDACTED_ID_2/REDACTED_ID_2/g" \
    -e "s/REDACTED_ID_3/REDACTED_ID_3/g" \
    -e "s/REDACTED_ID_4/REDACTED_ID_4/g" \
    -e "s/REDACTED_ID_5/REDACTED_ID_5/g" \
    {} +
