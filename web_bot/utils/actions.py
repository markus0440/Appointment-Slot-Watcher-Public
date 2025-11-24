from selenium.webdriver.common.by import By

def input_login(driver, login_id, login_value):
    username = driver.find_element(By.ID, f'{login_id}')
    username.send_keys(f'{login_value}')

def input_password(driver, password_id, password_value):
    username = driver.find_element(By.ID, f'{password_id}')
    username.send_keys(f'{password_value}')

def press_button(driver, button_id):
    button = driver.find_element(By.ID, f'{button_id}')
    button.click()