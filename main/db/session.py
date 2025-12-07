import psycopg2

conn = psycopg2.connect(
    "dbname=home_surveillance_db"
    "user=postgres"
    "password=12345"
    "host=192.168.100.8"
    "port=5432")

cursor = conn.cursor()