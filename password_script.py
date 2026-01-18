import bcrypt

password = b"!"

hashed = bcrypt.hashpw(password, bcrypt.gensalt())

print()
print()
print()
print(hashed.decode())
print()
print()
print()
print()
