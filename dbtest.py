import pymysql

mydb = pymysql.connect(
    host="localhost",
    user="root",
    password="amniotic-rake-music",
    database="sample"
)

# with mydb as mydb:
    # with mydb.cursor() as cursor:
    #     print("connection established")
#         # Create a new record
#         sql = "INSERT INTO `somestuff` (`words`, `numbers`) VALUES (%s, %s)"
#         cursor.execute(sql, ('why hello there', '12345134'))
#
#     # connection is not autocommit by default. So you must commit to save
#     # your changes.
#     mydb.commit()
#
#     with mydb.cursor() as cursor:
#         # Read a single record
#         sql = "SELECT * FROM `somestuff`"
#         cursor.execute(sql)
#         result = cursor.fetchone()
#         print(result)

def insertReusingConnection(words, numbers):
    with mydb.cursor() as cursor:
        sql = "INSERT INTO `somestuff` (`words`, `numbers`) VALUES (%s, %s)"
        cursor.execute(sql, (words, numbers))
        mydb.commit()

def insertWordsAndNumbers(words, numbers):
    # To connect MySQL database
    conn = pymysql.connect(
        host='localhost',
        user='root',
        password="amniotic-rake-music",
        database="sample"
    )

    cur = conn.cursor()

    # Select query
    sql = "INSERT INTO `somestuff` (`words`, `numbers`) VALUES (%s, %s)"
    cur.execute(sql, (words, numbers))
    conn.commit()
    # cur.execute("select * from `somestuff`")
    output = cur.fetchall()

    for i in output:
        print(i)

        # To close the connection
    conn.close()

# Driver Code
if __name__ == "__main__" :
    print("doing stuff")
    insertReusingConnection("this is from code", 908675130)