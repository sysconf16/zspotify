#! /usr/bin/env python3

"""
zspotify
SYSCONF¹⁶ fork of zspotify.
"""

import json
import os
import os.path
import platform
import re
import sys
import time
import shutil
from getpass import getpass

import music_tag
import requests
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.core import Session
from librespot.metadata import TrackId, EpisodeId
from pydub import AudioSegment
from tqdm import tqdm


SESSION: Session = None
sanitize = ["\\", "/", ":", "*", "?", "'", "<", ">", '"']

ROOT_PATH = "Music/zspotify/"
ROOT_PODCAST_PATH = "Podcasts/"
SKIP_EXISTING_FILES = True
MUSIC_FORMAT = os.getenv('MUSIC_FORMAT') or "mp3" # "mp3" | "ogg"
FORCE_PREMIUM = True # set to True if not detecting your premium account automatically
RAW_AUDIO_AS_IS = False or os.getenv('RAW_AUDIO_AS_IS') == "y" # set to True if you wish you save the raw audio without re-encoding it.
# This is how many seconds zspotify waits between downloading tracks so spotify doesn't get out the ban hammer
ANTI_BAN_WAIT_TIME = 240
ANTI_BAN_WAIT_TIME_ALBUMS = 480
# Set this to True to not wait at all between tracks and just go balls to the wall
OVERRIDE_AUTO_WAIT = False
CHUNK_SIZE = 64

LIMIT = 100 

requests.adapters.DEFAULT_RETRIES = 10

# miscellaneous functions for general use


def clear():
    """ Clear the console window """
    if platform.system() == "Windows":
        os.system("cls")
    else:
        os.system("clear")


def wait(seconds: int = 3):
    """ Pause for a set number of seconds """
    for i in range(seconds)[::-1]:
        print("\rWait for %d second(s)..." % (i + 1), end="")
        time.sleep(1)


def sanitize_data(value):
    """ Returns given string with problematic removed """
    global sanitize
    for i in sanitize:
        value = value.replace(i, "")
    return value.replace("|", "-")


def split_input(selection):
    """ Returns a list of inputted strings """
    if "-" in selection:
        return [i for i in range(int(selection.split("-")[0]),int(selection.split("-")[1]+1))] 
    else:
        return [i for i in selection.strip().split(" ")]


def splash():
    """ Displays splash screen """
    print("""
███████ ███████ ██████   ██████  ████████ ██ ███████ ██    ██
   ███  ██      ██   ██ ██    ██    ██    ██ ██       ██  ██
  ███   ███████ ██████  ██    ██    ██    ██ █████     ████
 ███         ██ ██      ██    ██    ██    ██ ██         ██
███████ ███████ ██       ██████     ██    ██ ██         ██
    """)


# two mains functions for logging in and doing client stuff
def login():
    """ Authenticates with Spotify and saves credentials to a file """
    global SESSION

    if os.path.isfile("/config/credentials.json"):
        shutil.copyfile('/config/credentials.json', 'credentials.json')

    if os.path.isfile("credentials.json"):
        try:
            SESSION = Session.Builder().stored_file().create()
            return
        except RuntimeError:
            pass
    while True:
        user_name = input("Username: ")
        password = getpass()
        try:
            SESSION = Session.Builder().user_pass(user_name, password).create()
            shutil.copyfile('credentials.json','/config/credentials.json')
            return
        except RuntimeError:
            pass


def client():
    """ Connects to spotify to perform query's and get songs to download """
    global QUALITY, SESSION
    splash()

    token = SESSION.tokens().get("user-read-email")

    if check_premium():
        print("[ DETECTED PREMIUM ACCOUNT - USING VERY_HIGH QUALITY ]\n\n")
        QUALITY = AudioQuality.VERY_HIGH
    else:
        print("[ DETECTED FREE ACCOUNT - USING HIGH QUALITY ]\n\n")
        QUALITY = AudioQuality.HIGH

    if len(sys.argv) > 1:
        if sys.argv[1] == "-p" or sys.argv[1] == "--playlist":
            download_from_user_playlist()
        elif sys.argv[1] == "-ls" or sys.argv[1] == "--liked-songs":
            for song in get_saved_tracks(token):
                if not song['track']['name']:
                    print(
                        "###   SKIPPING:  SONG DOES NOT EXISTS ON SPOTIFY ANYMORE   ###")
                else:
                    download_track(song['track']['id'], "Liked Songs/")
                print("\n")
        else:
            track_id_str, album_id_str, playlist_id_str, episode_id_str, show_id_str, artist_id_str = regex_input_for_urls(
                sys.argv[1])

            if track_id_str is not None:
                download_track(track_id_str)
            elif artist_id_str is not None:
                download_artist_albums(artist_id_str)
            elif album_id_str is not None:
                download_album(album_id_str)
            elif playlist_id_str is not None:
                playlist_songs = get_playlist_songs(token, playlist_id_str)
                name, creator = get_playlist_info(token, playlist_id_str)
                for song in playlist_songs:
                    download_track(song['track']['id'],
                                   sanitize_data(name) + "/")
                    print("\n")
            elif episode_id_str is not None:
                download_episode(episode_id_str)
            elif show_id_str is not None:
                for episode in get_show_episodes(token, show_id_str):
                    download_episode(episode)

    else:
        search_text = input("Enter search or URL: ")

        track_id_str, album_id_str, playlist_id_str, episode_id_str, show_id_str, artist_id_str = regex_input_for_urls(
            search_text)

        if track_id_str is not None:
            download_track(track_id_str)
        elif artist_id_str is not None:
            download_artist_albums(artist_id_str)
        elif album_id_str is not None:
            download_album(album_id_str)
        elif playlist_id_str is not None:
            playlist_songs = get_playlist_songs(token, playlist_id_str)
            name, creator = get_playlist_info(token, playlist_id_str)
            for song in playlist_songs:
                download_track(song['track']['id'],
                               sanitize_data(name) + "/")
                print("\n")
        elif episode_id_str is not None:
            download_episode(episode_id_str)
        elif show_id_str is not None:
            for episode in get_show_episodes(token, show_id_str):
                download_episode(episode)
        else:
            try:
                search(search_text)
            except:
                client()
            client()

    # wait()


def regex_input_for_urls(search_input):
    track_uri_search = re.search(
        r"^spotify:track:(?P<TrackID>[0-9a-zA-Z]{22})$", search_input)
    track_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/track/(?P<TrackID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    album_uri_search = re.search(
        r"^spotify:album:(?P<AlbumID>[0-9a-zA-Z]{22})$", search_input)
    album_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/album/(?P<AlbumID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    playlist_uri_search = re.search(
        r"^spotify:playlist:(?P<PlaylistID>[0-9a-zA-Z]{22})$", search_input)
    playlist_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/playlist/(?P<PlaylistID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    episode_uri_search = re.search(
        r"^spotify:episode:(?P<EpisodeID>[0-9a-zA-Z]{22})$", search_input)
    episode_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/episode/(?P<EpisodeID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    show_uri_search = re.search(
        r"^spotify:show:(?P<ShowID>[0-9a-zA-Z]{22})$", search_input)
    show_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/show/(?P<ShowID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    artist_uri_search = re.search(
        r"^spotify:artist:(?P<ArtistID>[0-9a-zA-Z]{22})$", search_input)
    artist_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/artist/(?P<ArtistID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    if track_uri_search is not None or track_url_search is not None:
        track_id_str = (track_uri_search
                        if track_uri_search is not None else
                        track_url_search).group("TrackID")
    else:
        track_id_str = None

    if album_uri_search is not None or album_url_search is not None:
        album_id_str = (album_uri_search
                        if album_uri_search is not None else
                        album_url_search).group("AlbumID")
    else:
        album_id_str = None

    if playlist_uri_search is not None or playlist_url_search is not None:
        playlist_id_str = (playlist_uri_search
                           if playlist_uri_search is not None else
                           playlist_url_search).group("PlaylistID")
    else:
        playlist_id_str = None

    if episode_uri_search is not None or episode_url_search is not None:
        episode_id_str = (episode_uri_search
                          if episode_uri_search is not None else
                          episode_url_search).group("EpisodeID")
    else:
        episode_id_str = None

    if show_uri_search is not None or show_url_search is not None:
        show_id_str = (show_uri_search
                       if show_uri_search is not None else
                       show_url_search).group("ShowID")
    else:
        show_id_str = None

    if artist_uri_search is not None or artist_url_search is not None:
        artist_id_str = (artist_uri_search
                         if artist_uri_search is not None else
                         artist_url_search).group("ArtistID")
    else:
        artist_id_str = None

    return track_id_str, album_id_str, playlist_id_str, episode_id_str, show_id_str, artist_id_str


def get_episode_info(episode_id_str):
    token = SESSION.tokens().get("user-read-email")
    info = json.loads(requests.get("https://api.spotify.com/v1/episodes/" +
                                   episode_id_str, headers={"Authorization": "Bearer %s" % token}).text)

    if "error" in info:
        return None, None
    else:
        # print(info['images'][0]['url'])
        return sanitize_data(info["show"]["name"]), sanitize_data(info["name"])


def get_show_episodes(access_token, show_id_str):
    """ returns episodes of a show """
    episodes = []
    offset = 0
    limit = 50

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'offset': offset}
        resp = requests.get(
            f'https://api.spotify.com/v1/shows/{show_id_str}/episodes', headers=headers, params=params).json()
        offset += limit
        for episode in resp["items"]:
            episodes.append(episode["id"])

        if len(resp['items']) < limit:
            break

    return episodes


def download_episode(episode_id_str):
    global ROOT_PODCAST_PATH, MUSIC_FORMAT

    podcast_name, episode_name = get_episode_info(episode_id_str)

    extra_paths = podcast_name + "/"

    if podcast_name is None:
        print("###   SKIPPING: (EPISODE NOT FOUND)   ###")
    else:
        filename = podcast_name + " - " + episode_name

        episode_id = EpisodeId.from_base62(episode_id_str)
        stream = SESSION.content_feeder().load(
            episode_id, VorbisOnlyAudioQuality(QUALITY), False, None)
        # print("###  DOWNLOADING '" + podcast_name + " - " +
        #      episode_name + "' - THIS MAY TAKE A WHILE ###")

        #if not os.path.isdir(ROOT_PODCAST_PATH + extra_paths):
        os.makedirs(ROOT_PODCAST_PATH + extra_paths,exist_ok=True)

        total_size = stream.input_stream.size
        with open(ROOT_PODCAST_PATH + extra_paths + filename + ".wav", 'wb') as file, tqdm(
                desc=filename,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024
        ) as bar:
            for _ in range(int(total_size / CHUNK_SIZE) + 1):
                bar.update(file.write(
                    stream.input_stream.stream().read(CHUNK_SIZE)))

        # convert_audio_format(ROOT_PODCAST_PATH +
        #                     extra_paths + filename + ".wav")

        # related functions that do stuff with the spotify API


def search(search_term):
    """ Searches Spotify's API for relevant data """
    token = SESSION.tokens().get("user-read-email")

    resp = requests.get(
        "https://api.spotify.com/v1/search",
        {
            "limit": LIMIT,
            "offset": "0",
            "q": search_term,
            "type": "track,album,playlist,artist"
        },
        headers={"Authorization": "Bearer %s" % token},
    )
    #print("token: ",token)

    i = 1
    tracks = resp.json()["tracks"]["items"]
    if len(tracks) > 0:
        print("###  TRACKS  ###")
        for track in tracks:
            if track["explicit"]:
                explicit = "[E]"
            else:
                explicit = ""
            print(f"{i}, {track['name']} {explicit} | {','.join([artist['name'] for artist in track['artists']])}")
            i += 1
        total_tracks = i - 1
        print("\n")
    else:
        total_tracks = 0

    albums = resp.json()["albums"]["items"]
    if len(albums) > 0:
        print("###  ALBUMS  ###")
        for album in albums:
            #print("==>",album,"\n")
            _year = re.search('(\d{4})', album['release_date']).group(1)
            print(f"{i}, ({_year}) {album['name']} [{album['total_tracks']}] | {','.join([artist['name'] for artist in album['artists']])}" )
            i += 1
        total_albums = i - total_tracks - 1
        print("\n")
    else:
        total_albums = 0

    playlists = resp.json()["playlists"]["items"]
    total_playlists = 0
    print("###  PLAYLISTS  ###")
    for playlist in playlists:
        print(f"{i}, {playlist['name']} | {playlist['owner']['display_name']}" )
        i += 1
    total_playlists = i - total_albums - total_tracks  - 1
    print("\n")

    artists = resp.json()["artists"]["items"]
    total_artists = 0
    print("###  ARTIST  ###")
    for artist in artists:
        #print("==> ",artist)
        print(f"{i}, {artist['name']} | {'/'.join(artist['genres'])}") 
        i += 1
    total_artists = i - total_albums - total_tracks - total_playlists - 1
    print("\n")

    if len(tracks) + len(albums) + len(playlists) == 0:
        print("NO RESULTS FOUND - EXITING...")
    else:

        selection = str(input("SELECT ITEM(S) BY ID: "))
        inputs = split_input(selection)
        
        if not selection: client()
        
        for pos in inputs:
            position = int(pos)
            if position <= total_tracks:
                track_id = tracks[position - 1]["id"]
                download_track(track_id)
            elif position <= total_albums + total_tracks:
                #print("==>" , position , " total_albums + total_tracks ", total_albums + total_tracks )
                download_album(albums[position - total_tracks - 1]["id"])
            elif position <= total_albums + total_tracks + total_playlists:
                #print("==> position: ", position ," total_albums + total_tracks + total_playlists ", total_albums + total_tracks + total_playlists )
                playlist_choice = playlists[position -
                                            total_tracks - total_albums - 1]
                playlist_songs = get_playlist_songs(token, playlist_choice['id'])
                for song in playlist_songs:
                    if song['track']['id'] is not None:
                        download_track(song['track']['id'], sanitize_data(
                            playlist_choice['name'].strip()) + "/")
                        print("\n")
            else:
                #5eyTLELpc4Coe8oRTHkU3F
                #print("==> position: ", position ," total_albums + total_tracks + total_playlists: ", position - total_albums - total_tracks - total_playlists )
                artists_choice = artists[position - total_albums - total_tracks - total_playlists - 1]
                albums = get_albums_artist(token,artists_choice['id'])
                i=0

                print("\n")
                print("ALL ALBUMS: ",len(albums)," IN:",str(set(album['album_type'] for album in albums)))
                
                for album in albums:
                    if artists_choice['id'] == album['artists'][0]['id'] and album['album_type'] != 'single':
                        i += 1
                        year = re.search('(\d{4})', album['release_date']).group(1)
                        print(f" {i} {album['artists'][0]['name']} - ({year}) {album['name']} [{album['total_tracks']}] [{album['album_type']}]")
                total_albums_downloads = i
                print("\n")

                #print('\n'.join([f"{album['name']} - [{album['album_type']}] | {'/'.join([artist['name'] for artist in album['artists']])} " for album in sorted(albums, key=lambda k: k['album_type'], reverse=True)]))

                
                for i in range(8)[::-1]:
                    print("\rWait for Download in %d second(s)..." % (i + 1), end="")
                    time.sleep(1)
                
                print("\n")
                i=0
                for album in albums:
                    if artists_choice['id'] == album['artists'][0]['id'] and album['album_type'] != 'single' :
                        i += 1
                        year = re.search('(\d{4})', album['release_date']).group(1)
                        print(f"\n\n\n{i}/{total_albums_downloads} {album['artists'][0]['name']} - ({year}) {album['name']} [{album['total_tracks']}]")
                        download_album(album['id'])
                        for i in range(ANTI_BAN_WAIT_TIME_ALBUMS)[::-1]:
                            print("\rWait for Next Download in %d second(s)..." % (i + 1), end="")
                            time.sleep(1)

def get_song_info(song_id):
    """ Retrieves metadata for downloaded songs """
    token = SESSION.tokens().get("user-read-email")
    try:

        info = json.loads(requests.get("https://api.spotify.com/v1/tracks?ids=" + song_id +
                        '&market=from_token', headers={"Authorization": "Bearer %s" % token}).text)

        artists = []
        for data in info['tracks'][0]['artists']:
            artists.append(sanitize_data(data['name']))
        album_name = sanitize_data(info['tracks'][0]['album']["name"])
        name = sanitize_data(info['tracks'][0]['name'])
        image_url = info['tracks'][0]['album']['images'][0]['url']
        release_year = info['tracks'][0]['album']['release_date'].split("-")[0]
        disc_number = info['tracks'][0]['disc_number']
        track_number = info['tracks'][0]['track_number']
        scraped_song_id = info['tracks'][0]['id']
        is_playable = info['tracks'][0]['is_playable']

        return artists, album_name, name, image_url, release_year, disc_number, track_number, scraped_song_id, is_playable
    except Exception as e:
        print("###   get_song_info - FAILED TO QUERY METADATA   ###")
        print(e)
        print(song_id,info)

def check_premium():
    """ If user has spotify premium return true """
    global FORCE_PREMIUM
    return bool((SESSION.get_user_attribute("type") == "premium") or FORCE_PREMIUM)


# Functions directly related to modifying the downloaded audio and its metadata
def convert_audio_format(filename):
    """ Converts raw audio into playable mp3 or ogg vorbis """
    global MUSIC_FORMAT
    #print("###   CONVERTING TO " + MUSIC_FORMAT.upper() + "   ###")
    raw_audio = AudioSegment.from_file(filename, format="ogg",
                                       frame_rate=44100, channels=2, sample_width=2)
    if QUALITY == AudioQuality.VERY_HIGH:
        bitrate = "320k"
    else:
        bitrate = "160k"
    raw_audio.export(filename, format=MUSIC_FORMAT, bitrate=bitrate)


def set_audio_tags(filename, artists, name, album_name, release_year, disc_number, track_number, track_id_str):
    """ sets music_tag metadata """
    #print("###   SETTING MUSIC TAGS   ###")
    tags = music_tag.load_file(filename)
    tags['artist'] = conv_artist_format(artists)
    tags['tracktitle'] = name
    tags['album'] = album_name
    tags['year'] = release_year
    tags['tracknumber'] = track_number
    tags.save()


def set_music_thumbnail(filename, image_url):
    """ Downloads cover artwork """
    #print("###   SETTING THUMBNAIL   ###")
    img = requests.get(image_url).content
    tags = music_tag.load_file(filename)
    tags['artwork'] = img
    tags.save()


def conv_artist_format(artists):
    """ Returns converted artist format """
    formatted = ""
    for artist in artists:
        formatted += artist + ", "
    return formatted[:-2]


# Extra functions directly related to spotify playlists
def get_all_playlists(access_token):
    """ Returns list of users playlists """
    playlists = []
    limit = 50
    offset = 0

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'offset': offset}
        resp = requests.get("https://api.spotify.com/v1/me/playlists",
                            headers=headers, params=params).json()
        offset += limit
        playlists.extend(resp['items'])

        if len(resp['items']) < limit:
            break

    return playlists


def get_playlist_songs(access_token, playlist_id):
    """ returns list of songs in a playlist """
    songs = []
    offset = 0
    limit = 100

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'offset': offset}
        resp = requests.get(
            f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks', headers=headers, params=params).json()
        offset += limit
        songs.extend(resp['items'])

        if len(resp['items']) < limit:
            break

    return songs


def get_playlist_info(access_token, playlist_id):
    """ Returns information scraped from playlist """
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get(
        f'https://api.spotify.com/v1/playlists/{playlist_id}?fields=name,owner(display_name)&market=from_token', headers=headers).json()
    return resp['name'].strip(), resp['owner']['display_name'].strip()


# Extra functions directly related to spotify albums
def get_album_tracks(access_token, album_id):
    """ Returns album tracklist """
    songs = []
    offset = 0
    limit = 50
    include_groups = 'album,compilation'

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'include_groups':include_groups, 'offset': offset}
        resp = requests.get(
            f'https://api.spotify.com/v1/albums/{album_id}/tracks', headers=headers, params=params).json()
        offset += limit
        songs.extend(resp['items'])

        if len(resp['items']) < limit:
            break

    return songs


def get_album_name(access_token, album_id):
    """ Returns album name """
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get(
        f'https://api.spotify.com/v1/albums/{album_id}', headers=headers).json()
    
    #_yearalbum = re.search('(\d{4})', resp['release_date']).group(1)
    #print(f"\n {resp['name']} - {_yearalbum} [{resp['total_tracks']}]")

    if m := re.search('(\d{4})', resp['release_date']):
        return resp['artists'][0]['name'], m.group(1),sanitize_data(resp['name']),resp['total_tracks']
    else: return resp['artists'][0]['name'], resp['release_date'],sanitize_data(resp['name']),resp['total_tracks']


def get_artist_albums(access_token, artist_id):
    """ Returns artist's albums """
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get(
        f'https://api.spotify.com/v1/artists/{artist_id}/albums', headers=headers).json()
    # Return a list each album's id
    return [resp['items'][i]['id'] for i in range(len(resp['items']))]

# Extra functions directly related to our saved tracks


def get_saved_tracks(access_token):
    """ Returns user's saved tracks """
    songs = []
    offset = 0
    limit = 50

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'offset': offset}
        resp = requests.get('https://api.spotify.com/v1/me/tracks',
                            headers=headers, params=params).json()
        offset += limit
        songs.extend(resp['items'])

        if len(resp['items']) < limit:
            break

    return songs


# Functions directly related to downloading stuff
def download_track(track_id_str: str, extra_paths="", prefix=False, prefix_value='', disable_progressbar=False):
    """ Downloads raw song audio from Spotify """
    global ROOT_PATH, SKIP_EXISTING_FILES, MUSIC_FORMAT, RAW_AUDIO_AS_IS, ANTI_BAN_WAIT_TIME, OVERRIDE_AUTO_WAIT
    try:
    	# TODO: ADD disc_number IF > 1 
        artists, album_name, name, image_url, release_year, disc_number, track_number, scraped_song_id, is_playable = get_song_info(
            track_id_str)

        _artist = artists[0]
        if prefix:
            _track_number = str(track_number).zfill(2)
            song_name = f'{_artist} - {album_name} - {_track_number}. {name}.{MUSIC_FORMAT}' 
            filename = os.path.join(ROOT_PATH, extra_paths, song_name)
        else:
            song_name = f'{_artist} - {album_name} - {name}.{MUSIC_FORMAT}' 
            filename = os.path.join(ROOT_PATH, extra_paths, song_name)


    except Exception as e:
        print("###   SKIPPING SONG - FAILED TO QUERY METADATA   ###")
        print(f" download_track FAILED: [{track_id_str}][{extra_paths}][{prefix}][{prefix_value}][{disable_progressbar}]")
        print("SKIPPING SONG: ",e)
        print(f" download_track FAILED: [{artists}][{album_name}][{name}][{image_url}][{release_year}][{disc_number}][{track_number}][{scraped_song_id}][{is_playable}]")
        time.sleep(60)
        download_track(track_id_str, extra_paths,prefix=prefix, prefix_value=prefix_value, disable_progressbar=disable_progressbar)

    else:

        try:
            if not is_playable:
                print("###   SKIPPING:", song_name, "(SONG IS UNAVAILABLE)   ###")
            else:
                if os.path.isfile(filename) and os.path.getsize(filename) and SKIP_EXISTING_FILES:
                    print("###   SKIPPING: (SONG ALREADY EXISTS) :", song_name, "   ###")
                else:
                    if track_id_str != scraped_song_id:
                        track_id_str = scraped_song_id

                    track_id = TrackId.from_base62(track_id_str)
                    # print("###   FOUND SONG:", song_name, "   ###")

                    stream = SESSION.content_feeder().load(
                        track_id, VorbisOnlyAudioQuality(QUALITY), False, None)
                    # print("###   DOWNLOADING RAW AUDIO   ###")

                    #if not os.path.isdir(ROOT_PATH + extra_paths):
                    os.makedirs(ROOT_PATH + extra_paths,exist_ok=True)

                    total_size = stream.input_stream.size
                    with open(filename, 'wb') as file, tqdm(
                            desc=song_name,
                            total=total_size,
                            unit='B',
                            unit_scale=True,
                            unit_divisor=1024,
                            disable=disable_progressbar
                    ) as bar:
                        for _ in range(int(total_size / CHUNK_SIZE) + 1):
                            bar.update(file.write(
                                stream.input_stream.stream().read(CHUNK_SIZE)))

                    if not RAW_AUDIO_AS_IS:
                        convert_audio_format(filename)
                        set_audio_tags(filename, artists, name, album_name,
                                       release_year, disc_number, track_number, track_id_str)
                        set_music_thumbnail(filename, image_url)

                    if not OVERRIDE_AUTO_WAIT:
                        time.sleep(ANTI_BAN_WAIT_TIME)
        except:
            print("###   SKIPPING:", song_name, "(GENERAL DOWNLOAD ERROR)   ###")
            if os.path.exists(filename):
                os.remove(filename)
            print(f" download_track GENERAL DOWNLOAD ERROR: [{track_id_str}][{extra_paths}][{prefix}][{prefix_value}][{disable_progressbar}]")
            download_track(track_id_str, extra_paths,prefix=prefix, prefix_value=prefix_value, disable_progressbar=disable_progressbar)


def download_album(album):
    """ Downloads songs from an album """
    token = SESSION.tokens().get("user-read-email")
    artist, album_release_date, album_name, total_tracks = get_album_name(token, album)
    tracks = get_album_tracks(token, album)
    print(f"\n  {artist} - ({album_release_date}) {album_name} [{total_tracks}]")
    disc_number_flag = False
    for track in tracks:
        if track['disc_number'] > 1:
            disc_number_flag = True
    if disc_number_flag: 
        for n, track in tqdm(enumerate(tracks, start=1), unit_scale=True, unit='Song', total=len(tracks)):
            disc_number = str(track['disc_number']).zfill(2)
            download_track(track['id'], os.path.join(artist, f"{artist} - {album_release_date} - {album_name}", f"CD {disc_number}"),prefix=True, prefix_value=str(n), disable_progressbar=True)
    else: 
        for n, track in tqdm(enumerate(tracks, start=1), unit_scale=True, unit='Song', total=len(tracks)):
            download_track(track['id'], os.path.join(artist, f"{artist} - {album_release_date} - {album_name}"),prefix=True, prefix_value=str(n), disable_progressbar=True)

def download_artist_albums(artist):
    """ Downloads albums of an artist """
    token = SESSION.tokens().get("user-read-email")
    albums = get_artist_albums(token, artist)
    for album_id in albums:
        download_album(album_id)

def get_albums_artist(access_token, artists_id):
    """ returns list of albums in a artist """

    offset = 0
    limit = 50
    include_groups = 'album,compilation'

    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'limit': limit, 'include_groups': include_groups, 'offset': offset}

    resp = requests.get(
        f'https://api.spotify.com/v1/artists/{artists_id}/albums', headers=headers, params=params).json()
    #print("###   Album Name:", resp['items'], "###")
    return resp['items']

def download_playlist(playlists, playlist_choice):
    """Downloads all the songs from a playlist"""
    token = SESSION.tokens().get("user-read-email")

    playlist_songs = get_playlist_songs(
        token, playlists[int(playlist_choice) - 1]['id'])

    for song in playlist_songs:
        if song['track']['id'] is not None:
            download_track(song['track']['id'], sanitize_data(
                playlists[int(playlist_choice) - 1]['name'].strip()) + "/")
        print("\n")


def download_from_user_playlist():
    """ Select which playlist(s) to download """
    token = SESSION.tokens().get("user-read-email")
    playlists = get_all_playlists(token)

    count = 1
    for playlist in playlists:
        print(str(count) + ": " + playlist['name'].strip())
        count += 1

    print("\n> SELECT A PLAYLIST BY ID")
    print("> SELECT A RANGE BY ADDING A DASH BETWEEN BOTH ID's")
    print("> For example, typing 10 to get one playlist or 10-20 to get\nevery playlist from 10-20 (inclusive)\n")

    playlist_choices = input("ID(s): ").split("-")

    if len(playlist_choices) == 1:
        download_playlist(playlists, playlist_choices[0])
    else:
        start = int(playlist_choices[0])
        end = int(playlist_choices[1]) + 1

        print(f"Downloading from {start} to {end}...")

        for playlist in range(start, end):
            download_playlist(playlists, playlist)

        print("\n**All playlists have been downloaded**\n")


# Core functions here

def check_raw():
    global RAW_AUDIO_AS_IS, MUSIC_FORMAT
    if RAW_AUDIO_AS_IS:
        MUSIC_FORMAT = "wav"


def main():
    """ Main function """
    check_raw()
    login()
    client()


if __name__ == "__main__":
    main()